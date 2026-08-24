import os
import json
import hmac
import logging
from datetime import date
from fastapi import APIRouter, Header, HTTPException
from database import get_conn

logger = logging.getLogger(__name__)
router = APIRouter()

# Firebase Admin lazy init — expects FIREBASE_SERVICE_ACCOUNT_JSON (JSON string) or
# FIREBASE_SERVICE_ACCOUNT_JSON_B64 or a file at /etc/secrets/firebase.json (Render)
_firebase_inited = False

def _ensure_firebase():
    global _firebase_inited
    if _firebase_inited:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials
        # Already inited?
        try:
            firebase_admin.get_app()
            _firebase_inited = True
            return True
        except ValueError:
            pass
        # Try env var JSON
        sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON_B64")
        if sa_json:
            # Handle base64
            if sa_json.strip().startswith("{"):
                info = json.loads(sa_json)
            else:
                import base64
                info = json.loads(base64.b64decode(sa_json).decode())
            cred = credentials.Certificate(info)
            firebase_admin.initialize_app(cred)
            _firebase_inited = True
            logger.info("Firebase Admin inited from env")
            return True
        # Try file (Render secret file)
        for p in ["/etc/secrets/firebase.json", "firebase-service-account.json"]:
            if os.path.exists(p):
                cred = credentials.Certificate(p)
                firebase_admin.initialize_app(cred)
                _firebase_inited = True
                logger.info("Firebase Admin inited from %s", p)
                return True
        logger.warning("Firebase Admin not configured — no service account found (set FIREBASE_SERVICE_ACCOUNT_JSON)")
        return False
    except Exception as e:
        logger.warning("Firebase Admin init failed: %s", e)
        return False

# Choice per spec Phase 2.2: POST /internal/notify-scraper-run with shared secret
# Requires fewer changes to confNotifier workflow than direct FCM from that repo
# (just add `curl -H "X-Notify-Secret: $NOTIFY_SECRET" $API/internal/notify-scraper-run` after UPSERT).

@router.post("/internal/notify-scraper-run")
def notify_scraper_run(x_notify_secret: str = Header(None)):
    expected = os.environ.get("NOTIFY_SECRET", "")
    if not expected or not x_notify_secret or not hmac.compare_digest(x_notify_secret, expected):
        raise HTTPException(status_code=401, detail="Invalid secret")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT fcm_token FROM device_tokens")
        tokens = [r[0] for r in cur.fetchall() if r[0]]
        cur.close()
        count = len(tokens)
        logger.info("notify-scraper-run: %d device(s) to notify (daily digest)", count)
        # Invalidate cached conference reads — scraper just upserted
        try:
            from cache import invalidate_prefix
            invalidate_prefix("cal:")
            invalidate_prefix("upcoming:")
            invalidate_prefix("conf:")
        except Exception:
            pass
        if count == 0:
            return {"ok": True, "devices": 0, "sent": 0, "message": "No devices"}
        if not _ensure_firebase():
            return {"ok": True, "devices": count, "sent": 0, "message": "Check today's conference updates (FCM not configured)"}
        # Send via FCM — single daily digest, defer per-conference diff
        try:
            import firebase_admin.messaging as fcm
            # FCM multicast max 500 per call
            sent = 0
            for i in range(0, len(tokens), 500):
                batch = tokens[i:i+500]
                msg = fcm.MulticastMessage(
                    notification=fcm.Notification(title="Call4Paper", body="Check today's conference updates"),
                    data={"type": "daily_digest", "screen": "calendar"},
                    tokens=batch,
                )
                resp = fcm.send_each_for_multicast(msg)
                sent += resp.success_count
                if resp.failure_count:
                    logger.warning("FCM batch %d: %d failures", i//500, resp.failure_count)
            logger.info("FCM daily digest sent to %d/%d", sent, count)
            return {"ok": True, "devices": count, "sent": sent, "message": "Check today's conference updates"}
        except Exception as e:
            logger.error("FCM send failed: %s", e)
            raise HTTPException(status_code=500, detail=f"FCM failed: {e}")
    finally:
        conn.close()


@router.post("/internal/notify-bookmarks")
def notify_bookmarks(x_notify_secret: str = Header(None)):
    if not hmac.compare_digest(x_notify_secret or "", os.environ.get("NOTIFY_SECRET", "")):
        raise HTTPException(status_code=401, detail="Invalid secret")

    conn = get_conn()
    try:
        cur = conn.cursor()
        # Find bookmarked conferences with approaching or changed deadlines,
        # excluding already-notified combinations via notification_log.
        # Includes deadline_date in dedup key so A→B→C each gets a fresh slot.
        cur.execute("""
            SELECT dt.fcm_token, dt.user_id, conf.id AS conf_id, conf.title,
                   dl.dl_type, dl.deadline_date,
                   CASE
                     WHEN dl.previous_date IS DISTINCT FROM dl.deadline_date AND dl.previous_date IS NOT NULL THEN 'changed'
                     WHEN dl.deadline_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '3 days' THEN 'approaching'
                   END AS reason
            FROM device_tokens dt
            JOIN bookmarks b ON b.user_id = dt.user_id
            JOIN conferences conf ON conf.id = b.conference_id
            CROSS JOIN LATERAL (
                VALUES
                    ('abstract',         conf.abstract_deadline,         conf.abstract_deadline_previous),
                    ('full_paper',       conf.full_paper_deadline,       conf.full_paper_deadline_previous)
            ) AS dl(dl_type, deadline_date, previous_date)
            LEFT JOIN notification_log nl
              ON nl.user_id = dt.user_id
             AND nl.conference_id = conf.id
             AND nl.deadline_type = dl.dl_type
             AND nl.deadline_date = dl.deadline_date
             AND nl.reason = CASE
                   WHEN dl.previous_date IS DISTINCT FROM dl.deadline_date AND dl.previous_date IS NOT NULL THEN 'changed'
                   WHEN dl.deadline_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '3 days' THEN 'approaching'
                 END
            WHERE dl.deadline_date IS NOT NULL
              AND CASE
                    WHEN dl.previous_date IS DISTINCT FROM dl.deadline_date AND dl.previous_date IS NOT NULL THEN 'changed'
                    WHEN dl.deadline_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '3 days' THEN 'approaching'
                  END IS NOT NULL
              AND nl.id IS NULL
        """)
        rows = cur.fetchall()
        cur.close()

        if not rows:
            return {"ok": True, "targets": 0, "sent": 0, "message": "No approaching/changed deadlines"}

        if not _ensure_firebase():
            return {"ok": True, "targets": len(rows), "sent": 0, "message": "FCM not configured"}

        import firebase_admin.messaging as fcm

        # Group by user to avoid sending multiple notifications per device
        user_tokens = {}
        user_payloads = {}  # user_id -> list of (conf_id, title, dl_type, reason, deadline_date)
        for r in rows:
            fcm_token, user_id, conf_id, title, dl_type, deadline_date, reason = r
            user_tokens.setdefault(user_id, set()).add(fcm_token)
            user_payloads.setdefault(user_id, []).append((conf_id, title, dl_type, reason, deadline_date))

        sent = 0
        # Track which users actually received at least one token success — only log those
        succeeded_users = set()
        for user_id, tokens_set in user_tokens.items():
            token_list = list(tokens_set)
            payloads = user_payloads[user_id]

            # Build per-conference notification bodies
            if len(payloads) == 1:
                conf_id, title, dl_type, reason, deadline_date = payloads[0]
                if reason == "changed":
                    body = f"Deadline updated for {title}"
                else:
                    days_left = (deadline_date - date.today()).days
                    body = f"{title} — {dl_type.replace('_', ' ')} due in {days_left}d"
                data = {
                    "type": "deadline_change",
                    "conference_id": str(conf_id),
                    "screen": "calendar",
                }
            else:
                # Multiple conferences — generic list body
                names = ", ".join(p[1] for p in payloads[:3])
                suffix = f" +{len(payloads) - 3}" if len(payloads) > 3 else ""
                body = f"Deadlines approaching: {names}{suffix}"
                data = {"type": "deadline_change", "screen": "upcoming"}

            user_success = False
            for i in range(0, len(token_list), 500):
                batch = token_list[i:i + 500]
                msg = fcm.MulticastMessage(
                    notification=fcm.Notification(title="Call4Paper", body=body),
                    data=data,
                    tokens=batch,
                )
                resp = fcm.send_each_for_multicast(msg)
                # Per-token detail — don't count batch as success if all tokens in batch failed
                batch_success = 0
                try:
                    for idx, r in enumerate(resp.responses):
                        if r.success:
                            batch_success += 1
                        else:
                            # Log stale token for cleanup; exception holds the error
                            tok = batch[idx] if idx < len(batch) else "unknown"
                            logger.info("notify-bookmarks token failed user=%s token=%s.. err=%s", user_id, tok[:12], r.exception)
                except Exception as e:
                    logger.warning("notify-bookmarks response parse failed user=%s: %s", user_id, e)
                    batch_success = resp.success_count

                sent += batch_success
                if batch_success > 0:
                    user_success = True

                if resp.failure_count:
                    logger.warning("notify-bookmarks user %s batch %d: %d failures",
                                   user_id, i // 500, resp.failure_count)

            if user_success:
                succeeded_users.add(user_id)

        # Record only what was actually delivered — per-row commit so one FK race doesn't wipe 1..49
        # Also, when a 'changed' fires, delete any prior 'approaching' for same (user, conference, type) so the 3-day warning can fire again for the new date
        inserted = 0
        cur2 = conn.cursor()
        for r in rows:
            fcm_token, user_id, conf_id, title, dl_type, deadline_date, reason = r
            if user_id not in succeeded_users:
                continue
            try:
                if reason == "changed":
                    # Allow the approaching countdown to restart for the new date
                    cur2.execute(
                        "DELETE FROM notification_log WHERE user_id=%s AND conference_id=%s AND deadline_type=%s AND reason='approaching'",
                        (user_id, conf_id, dl_type)
                    )
                cur2.execute("""
                    INSERT INTO notification_log (user_id, conference_id, deadline_type, deadline_date, reason)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, conference_id, deadline_type, reason, deadline_date) DO NOTHING
                """, (user_id, conf_id, dl_type, deadline_date, reason))
                if cur2.rowcount:
                    inserted += 1
                conn.commit()
            except Exception as e:
                logger.error("notify-bookmarks log insert failed user=%s conf=%s type=%s reason=%s date=%s: %s", user_id, conf_id, dl_type, reason, deadline_date, e)
                try:
                    conn.rollback()
                except Exception:
                    pass
                # Continue to next row — don't break and wipe previous commits
                continue
        cur2.close()

        logger.info("notify-bookmarks: %d targets, %d sent, %d logged", len(rows), sent, inserted)
        return {"ok": True, "targets": len(rows), "sent": sent, "logged": inserted}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.post("/internal/notify-digest")
def notify_digest(time_of_day: str = "morning", x_notify_secret: str = Header(None)):
    if not hmac.compare_digest(x_notify_secret or "", os.environ.get("NOTIFY_SECRET", "")):
        raise HTTPException(status_code=401, detail="Invalid secret")
    if time_of_day not in ("morning", "evening"):
        raise HTTPException(status_code=400, detail="time_of_day must be 'morning' or 'evening'")
    if not _ensure_firebase():
        return {"ok": True, "sent": False, "message": "FCM not configured"}

    body = (
        "Good morning — check today's CFP deadlines"
        if time_of_day == "morning"
        else "Evening check-in — anything closing soon?"
    )

    try:
        import firebase_admin.messaging as fcm
        fcm.send(fcm.Message(
            notification=fcm.Notification(title="Call4Paper", body=body),
            data={"type": "reminder", "screen": "upcoming"},
            topic="all_users",
        ))
        logger.info("notify-digest: sent %s digest via topic", time_of_day)
        return {"ok": True, "sent": True, "topic": "all_users"}
    except Exception as e:
        logger.error("notify-digest failed: %s", e)
        raise HTTPException(status_code=500, detail=f"FCM failed: {e}")
