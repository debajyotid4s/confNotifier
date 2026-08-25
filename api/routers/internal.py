"""Internal endpoints called by scheduled jobs, gated by a shared secret.

  POST /internal/notify-scraper-run   after a scraper pass: bust caches, digest push
  POST /internal/notify-bookmarks     per-user alerts for bookmarked deadlines
  POST /internal/notify-digest        morning/evening broadcast to the topic
  POST /internal/notify-daily         one combined daily engagement pass

Every handler is idempotent within its window: a Redis marker suppresses repeats,
so a cron misfire (or a retry loop) cannot spam users. `notification_log` provides
the durable per-user dedup that survives a Redis flush.

The three-level SQL fallback that used to guard against a pre-migration
production schema has been removed: migration_005/006/011 are now prerequisites,
and the fallbacks made the real query impossible to read or index for.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import execute_values

from database import db_cursor, fetch_all
from deps import require_internal_secret

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_internal_secret)])

#: FCM accepts at most 500 tokens per multicast call.
FCM_BATCH = 500

DAY_SECONDS = 24 * 3600
HOUR_SECONDS = 3600

#: Topic every installed app subscribes to, used for broadcasts.
BROADCAST_TOPIC = "all_users"

_firebase_inited = False


def _ensure_firebase() -> bool:
    """Initialise Firebase Admin once, from env JSON, base64 env, or a secret file."""
    global _firebase_inited
    if _firebase_inited:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials

        try:
            firebase_admin.get_app()
            _firebase_inited = True
            return True
        except ValueError:
            pass

        raw = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
               or os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON_B64"))
        if raw:
            if raw.strip().startswith("{"):
                info = json.loads(raw)
            else:
                import base64

                info = json.loads(base64.b64decode(raw).decode())
            firebase_admin.initialize_app(credentials.Certificate(info))
            _firebase_inited = True
            logger.info("Firebase Admin initialised from env")
            return True

        for path in ("/etc/secrets/firebase.json", "firebase-service-account.json"):
            if os.path.exists(path):
                firebase_admin.initialize_app(credentials.Certificate(path))
                _firebase_inited = True
                logger.info("Firebase Admin initialised from %s", path)
                return True

        logger.warning("Firebase Admin not configured — set FIREBASE_SERVICE_ACCOUNT_JSON")
        return False
    except Exception as e:
        logger.warning("Firebase Admin init failed: %s", e)
        return False


# ── Idempotency markers ───────────────────────────────────────────────────────

def _already_sent(key: str) -> bool:
    """True when this job already ran inside its window."""
    try:
        from cache import get_redis

        redis = get_redis()
        return bool(redis and redis.get(key) is not None)
    except Exception:
        return False


def _mark_sent(key: str, ttl: int) -> None:
    try:
        from cache import get_redis

        redis = get_redis()
        if redis:
            redis.setex(key, ttl, "1")
    except Exception:
        pass


def _invalidate_conference_caches() -> None:
    """Drop cached conference reads after the scraper writes."""
    try:
        from cache import invalidate_conference_reads

        invalidate_conference_reads()
    except Exception as e:
        logger.warning("cache invalidation failed: %s", e)


# ── FCM helpers ───────────────────────────────────────────────────────────────

def _all_device_tokens() -> list[str]:
    rows = fetch_all("SELECT fcm_token FROM device_tokens WHERE fcm_token IS NOT NULL")
    return [row[0] for row in rows]


def _send_multicast(tokens: list[str], title: str, body: str, data: dict) -> tuple[int, list[str]]:
    """Send to many tokens. Returns (success_count, tokens FCM rejected).

    Rejected tokens are returned so the caller can delete them: an uninstalled app
    leaves a dead token behind forever otherwise, and every future send pays for it.
    """
    import firebase_admin.messaging as fcm

    sent = 0
    dead: list[str] = []
    for start in range(0, len(tokens), FCM_BATCH):
        batch = tokens[start:start + FCM_BATCH]
        response = fcm.send_each_for_multicast(
            fcm.MulticastMessage(
                notification=fcm.Notification(title=title, body=body),
                data=data,
                tokens=batch,
            )
        )
        for token, result in zip(batch, response.responses):
            if result.success:
                sent += 1
                continue
            error = type(result.exception).__name__ if result.exception else "Unknown"
            if error in ("UnregisteredError", "SenderIdMismatchError", "InvalidArgumentError"):
                dead.append(token)
            logger.info("fcm token rejected (%s): %s...", error, token[:12])
    return sent, dead


def _send_topic(title: str, body: str, data: dict) -> None:
    import firebase_admin.messaging as fcm

    fcm.send(fcm.Message(
        notification=fcm.Notification(title=title, body=body),
        data=data,
        topic=BROADCAST_TOPIC,
    ))


def _prune_dead_tokens(tokens: list[str]) -> int:
    """Delete tokens FCM reported as permanently invalid."""
    if not tokens:
        return 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM device_tokens WHERE fcm_token = ANY(%s)", (tokens,))
            removed = cur.rowcount
        logger.info("pruned %d dead device token(s)", removed)
        return removed
    except Exception as e:
        logger.warning("dead-token prune failed: %s", e)
        return 0


# ── Digest copy ───────────────────────────────────────────────────────────────

def _upcoming_sample(days: int = 7, limit: int = 3) -> list[tuple[str, date]]:
    """Nearest deadlines within `days`, for building notification copy."""
    return fetch_all(
        """
        SELECT c.title, LEAST(
                   COALESCE(cd_abs.deadline,  c.abstract_deadline,  DATE '9999-12-31'),
                   COALESCE(cd_full.deadline, c.full_paper_deadline, DATE '9999-12-31')
               ) AS deadline
          FROM conferences c
          LEFT JOIN conference_deadlines cd_abs
                 ON cd_abs.conference_id = c.id AND cd_abs.type = 'abstract'
          LEFT JOIN conference_deadlines cd_full
                 ON cd_full.conference_id = c.id AND cd_full.type = 'full_paper'
         WHERE LEAST(
                   COALESCE(cd_abs.deadline,  c.abstract_deadline,  DATE '9999-12-31'),
                   COALESCE(cd_full.deadline, c.full_paper_deadline, DATE '9999-12-31')
               ) BETWEEN CURRENT_DATE AND CURRENT_DATE + %s::interval
         ORDER BY deadline ASC
         LIMIT %s
        """,
        (f"{days} days", limit),
    )


def _short_title(title: str, width: int = 30) -> str:
    return (title or "").split(",")[0].split("(")[0].strip()[:width]


def _digest_body(time_of_day: str) -> str:
    """Notification copy built from real upcoming deadlines."""
    greeting = "Good morning" if time_of_day == "morning" else "Evening check-in"
    try:
        rows = _upcoming_sample()
    except Exception as e:
        logger.warning("digest copy query failed: %s", e)
        rows = []

    if not rows:
        return (f"{greeting} — check today's CFP deadlines" if time_of_day == "morning"
                else f"{greeting} — anything closing soon?")

    title, deadline = rows[0]
    when = deadline.strftime("%b %d") if hasattr(deadline, "strftime") else str(deadline)
    count = len(rows)
    if time_of_day == "morning":
        return f"{greeting} — {_short_title(title)} deadline {when} — {count} this week"
    return f"{greeting} — {count} deadline(s) within 7 days, don't miss out"


# ── Bookmarked deadline alerts ────────────────────────────────────────────────

#: Why a user is being notified. Order matters: the first matching branch wins.
_REASON_SQL = """
    CASE
      WHEN dl.previous_date IS NOT NULL
       AND dl.previous_date IS DISTINCT FROM dl.deadline_date         THEN 'changed'
      WHEN dl.deadline_date = CURRENT_DATE + 1                        THEN 'urgent_24h'
      WHEN dl.deadline_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7 THEN 'approaching'
    END
"""

#: One row per (device, conference, deadline type) that needs a push.
#:
#: `notification_log` is LEFT JOINed on the full identity including deadline_date,
#: so an extension from A to B produces a fresh notification instead of being
#: deduped against the alert for A. 'approaching' is allowed to resend once a day
#: for engagement; 'changed' and 'urgent_24h' are sent once each.
_BOOKMARK_TARGETS_SQL = f"""
    WITH candidate AS (
        SELECT dt.fcm_token,
               dt.user_id,
               c.id    AS conference_id,
               c.title,
               dl.dl_type,
               dl.deadline_date,
               {_REASON_SQL} AS reason
          FROM device_tokens dt
          JOIN bookmarks   b ON b.user_id = dt.user_id
          JOIN conferences c ON c.id = b.conference_id
          LEFT JOIN conference_deadlines cd_abs
                 ON cd_abs.conference_id = c.id AND cd_abs.type = 'abstract'
          LEFT JOIN conference_deadlines cd_full
                 ON cd_full.conference_id = c.id AND cd_full.type = 'full_paper'
          CROSS JOIN LATERAL (
              VALUES
                ('abstract',
                 COALESCE(cd_abs.deadline,  c.abstract_deadline),
                 COALESCE(cd_abs.deadline_previous,  c.abstract_deadline_previous)),
                ('full_paper',
                 COALESCE(cd_full.deadline, c.full_paper_deadline),
                 COALESCE(cd_full.deadline_previous, c.full_paper_deadline_previous))
          ) AS dl(dl_type, deadline_date, previous_date)
         WHERE dl.deadline_date IS NOT NULL
    )
    SELECT candidate.fcm_token, candidate.user_id, candidate.conference_id,
           candidate.title, candidate.dl_type, candidate.deadline_date, candidate.reason
      FROM candidate
      LEFT JOIN notification_log nl
             ON nl.user_id       = candidate.user_id
            AND nl.conference_id = candidate.conference_id
            AND nl.deadline_type = candidate.dl_type
            AND nl.deadline_date = candidate.deadline_date
            AND nl.reason        = candidate.reason
            AND (candidate.reason <> 'approaching'
                 OR nl.notified_at::date = CURRENT_DATE)
     WHERE candidate.reason IS NOT NULL
       AND nl.id IS NULL
"""


@dataclass(frozen=True)
class Alert:
    """One pending push for one user."""

    conference_id: int
    title: str
    deadline_type: str
    reason: str
    deadline_date: date


def _alert_body(alerts: list[Alert]) -> tuple[str, dict]:
    """Notification copy and payload for one user's pending alerts."""
    if len(alerts) == 1:
        alert = alerts[0]
        kind = alert.deadline_type.replace("_", " ")
        if alert.reason == "changed":
            body = f"Deadline updated for {alert.title}"
        elif alert.reason == "urgent_24h":
            body = f"⏰ Deadline tomorrow — {alert.title} — submit now"
        else:
            days_left = (alert.deadline_date - date.today()).days
            if days_left <= 0:
                body = f"Today — {alert.title} deadline"
            elif days_left == 1:
                body = f"Tomorrow — {alert.title} — {kind}"
            else:
                body = f"{alert.title} — {kind} due in {days_left}d"
        return body, {
            "type": "deadline_change",
            "conference_id": str(alert.conference_id),
            "screen": "calendar",
        }

    urgent = [a for a in alerts if a.reason == "urgent_24h"]
    if urgent:
        names = ", ".join(a.title for a in urgent[:3])
        body = f"⏰ {len(urgent)} deadline(s) tomorrow — {names}"
    else:
        names = ", ".join(a.title for a in alerts[:3])
        suffix = f" +{len(alerts) - 3}" if len(alerts) > 3 else ""
        body = f"Deadlines approaching: {names}{suffix}"
    return body, {"type": "deadline_change", "screen": "upcoming"}


def _record_notifications(rows: list[tuple], delivered_users: set) -> int:
    """Log delivered alerts so they are not repeated.

    A 'changed' alert supersedes any pending 'approaching' row for the same
    deadline, so the user is not told twice about the same date.
    """
    entries = [
        (user_id, conference_id, dl_type, deadline_date, reason)
        for _token, user_id, conference_id, _title, dl_type, deadline_date, reason in rows
        if user_id in delivered_users
    ]
    if not entries:
        return 0

    superseded = [(u, c, t) for u, c, t, _d, reason in entries if reason == "changed"]
    try:
        with db_cursor(commit=True) as cur:
            for user_id, conference_id, dl_type in superseded:
                cur.execute(
                    "DELETE FROM notification_log WHERE user_id = %s AND conference_id = %s "
                    "AND deadline_type = %s AND reason = 'approaching'",
                    (user_id, conference_id, dl_type),
                )
            execute_values(
                cur,
                "INSERT INTO notification_log "
                "(user_id, conference_id, deadline_type, deadline_date, reason) VALUES %s "
                "ON CONFLICT (user_id, conference_id, deadline_type, reason, deadline_date) "
                "DO NOTHING",
                entries,
                template="(%s, %s, %s, %s, %s)",
            )
            return cur.rowcount if cur.rowcount != -1 else len(entries)
    except Exception as e:
        logger.error("notification_log insert failed: %s", e)
        return 0


@router.post("/internal/notify-bookmarks")
def notify_bookmarks():
    """Push deadline alerts for conferences users bookmarked."""
    marker = f"notify:bookmarks:{date.today().isoformat()}"
    if _already_sent(marker):
        logger.info("notify-bookmarks: already sent today, skipping")
        return {"ok": True, "targets": 0, "sent": 0, "message": "Already sent today"}

    try:
        rows = fetch_all(_BOOKMARK_TARGETS_SQL)
    except Exception as e:
        logger.error("notify-bookmarks: target query failed: %s", e)
        raise HTTPException(status_code=500, detail="Could not compute notification targets")

    if not rows:
        return {"ok": True, "targets": 0, "sent": 0, "message": "No approaching or changed deadlines"}
    if not _ensure_firebase():
        return {"ok": True, "targets": len(rows), "sent": 0, "message": "FCM not configured"}

    tokens_by_user: dict = {}
    alerts_by_user: dict = {}
    for token, user_id, conference_id, title, dl_type, deadline_date, reason in rows:
        tokens_by_user.setdefault(user_id, set()).add(token)
        alerts_by_user.setdefault(user_id, []).append(
            Alert(conference_id, title, dl_type, reason, deadline_date)
        )

    sent = 0
    delivered_users = set()
    dead_tokens: list[str] = []

    for user_id, tokens in tokens_by_user.items():
        body, data = _alert_body(alerts_by_user[user_id])
        try:
            user_sent, dead = _send_multicast(list(tokens), "Call4Paper", body, data)
        except Exception as e:
            logger.error("notify-bookmarks: send failed for user %s: %s", user_id, e)
            continue
        sent += user_sent
        dead_tokens += dead
        if user_sent:
            delivered_users.add(user_id)

    logged = _record_notifications(rows, delivered_users)
    _prune_dead_tokens(dead_tokens)

    if sent:
        _mark_sent(marker, DAY_SECONDS)
    logger.info("notify-bookmarks: %d target(s), %d sent, %d logged", len(rows), sent, logged)
    return {"ok": True, "targets": len(rows), "sent": sent, "logged": logged}


# ── Broadcasts ────────────────────────────────────────────────────────────────

@router.post("/internal/notify-scraper-run")
def notify_scraper_run():
    """Bust conference caches after a scraper pass and send one digest push."""
    _invalidate_conference_caches()

    marker = "notify:scraper-run:last"
    if _already_sent(marker):
        logger.info("notify-scraper-run: already sent within the hour, caches busted only")
        return {"ok": True, "devices": 0, "sent": 0, "message": "Rate limited — caches invalidated"}

    tokens = _all_device_tokens()
    if not tokens:
        return {"ok": True, "devices": 0, "sent": 0, "message": "No devices"}
    if not _ensure_firebase():
        return {"ok": True, "devices": len(tokens), "sent": 0, "message": "FCM not configured"}

    body = _digest_body("morning")
    try:
        sent, dead = _send_multicast(tokens, "Call4Paper", body,
                                     {"type": "daily_digest", "screen": "calendar"})
    except Exception as e:
        logger.error("notify-scraper-run: FCM send failed: %s", e)
        raise HTTPException(status_code=502, detail="FCM send failed")

    _prune_dead_tokens(dead)
    if sent:
        _mark_sent(marker, HOUR_SECONDS)
    logger.info("notify-scraper-run: %d/%d delivered", sent, len(tokens))
    return {"ok": True, "devices": len(tokens), "sent": sent, "message": body}


@router.post("/internal/notify-digest")
def notify_digest(time_of_day: str = Query("morning", pattern="^(morning|evening)$")):
    """Broadcast the morning or evening digest to the topic."""
    marker = f"notify:digest:{time_of_day}:{date.today().isoformat()}"
    if _already_sent(marker):
        logger.info("notify-digest: %s already sent today", time_of_day)
        return {"ok": True, "sent": False, "message": "Already sent today"}
    if not _ensure_firebase():
        return {"ok": True, "sent": False, "message": "FCM not configured"}

    body = _digest_body(time_of_day)
    try:
        _send_topic("Call4Paper", body, {"type": "reminder", "screen": "upcoming"})
    except Exception as e:
        logger.error("notify-digest failed: %s", e)
        raise HTTPException(status_code=502, detail="FCM send failed")

    _mark_sent(marker, DAY_SECONDS)
    logger.info("notify-digest: sent %s digest — %s", time_of_day, body[:60])
    return {"ok": True, "sent": True, "topic": BROADCAST_TOPIC, "body": body}


@router.post("/internal/notify-daily")
def notify_daily():
    """One daily pass: bust caches, broadcast the digest, then bookmark alerts.

    Intended for a single daily cron. Bookmark alerts are delegated to
    notify_bookmarks() rather than reimplemented — the previous version duplicated
    part of the query and reported a count without ever sending anything.
    """
    marker = f"notify:daily:{date.today().isoformat()}"
    if _already_sent(marker):
        logger.info("notify-daily: already sent today")
        return {"ok": True, "sent": False, "message": "Already sent today"}

    _invalidate_conference_caches()
    if not _ensure_firebase():
        return {"ok": True, "sent": False, "message": "FCM not configured"}

    results: dict = {"ok": True}

    body = _digest_body("morning")
    try:
        _send_topic("Call4Paper", body, {"type": "daily_digest", "screen": "upcoming"})
        results["broadcast"] = {"sent": True, "body": body}
    except Exception as e:
        logger.warning("notify-daily: broadcast failed: %s", e)
        results["broadcast"] = {"sent": False, "error": str(e)[:200]}

    try:
        results["bookmarks"] = notify_bookmarks()
    except HTTPException as e:
        results["bookmarks"] = {"ok": False, "error": e.detail}

    _mark_sent(marker, DAY_SECONDS)
    return results
