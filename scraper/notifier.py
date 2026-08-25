"""Telegram message construction and delivery.

Three entry points:
  notify()                            announce a newly discovered conference
  notify_pending()                    flush anything saved but not yet announced
  send_deadline_change_notification() report a verified deadline change

Messages are HTML, because the deadline-change format strikes through the old
date. Every posted message id is recorded so a false alert can be deleted.
"""

import logging
import os
import re
import time
from datetime import datetime

import requests

from scraper import db
from scraper.schema import SUBMISSION_TYPES, deadline_select_columns
from scraper.utils import escape_html, resolve_channel

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{}/{}"
NOTIFY_WINDOW_DAYS = 30
SEND_TIMEOUT = 15
#: Telegram tolerates roughly one message per second to a channel.
INTER_MESSAGE_SLEEP = 2

#: Human labels for the two announced deadline kinds.
_DEADLINE_LABELS = (("abstract_deadline", "Abstract"), ("full_paper_deadline", "Full paper"))


def _channel() -> str:
    """Configured channel as an @handle or numeric chat id."""
    return resolve_channel(
        os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
    )


def _make_hashtag(text) -> str:
    """PascalCase hashtag body from arbitrary text."""
    words = re.sub(r"[^a-zA-Z0-9\s]", "", str(text or "")).split()
    return "".join(w.capitalize() for w in words if w)


def _format_date(value) -> str:
    """Render a date as 'August 15, 2027', or 'TBA' when absent."""
    if not value:
        return "TBA"
    if hasattr(value, "strftime"):
        return value.strftime("%B %d, %Y")
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%B %d, %Y")
    except (ValueError, TypeError):
        return str(value)


def _post(method: str, payload: dict, timeout: int = SEND_TIMEOUT):
    """POST to the Telegram Bot API. Returns the parsed body or None."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return None
    try:
        resp = requests.post(TELEGRAM_API.format(token, method), json=payload, timeout=timeout)
    except requests.RequestException as e:
        logger.error("Telegram %s request error: %s", method, e)
        return None
    if resp.status_code == 200:
        try:
            return resp.json()
        except ValueError:
            return {}
    logger.error("Telegram %s failed (%d): %s", method, resp.status_code, resp.text[:300])
    return None


def send_plain_message(text: str, *, parse_mode: str = "HTML",
                       disable_web_page_preview: bool = True) -> int | bool:
    """Post a message to the configured channel.

    Returns the message id on success (truthy) or False on failure.
    """
    channel = _channel()
    if not channel:
        logger.error("TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK not set")
        return False

    payload = {"chat_id": channel, "text": text, "parse_mode": parse_mode}
    if disable_web_page_preview:
        payload["disable_web_page_preview"] = True

    body = _post("sendMessage", payload)
    if body is None:
        return False
    message_id = (body.get("result") or {}).get("message_id")
    return int(message_id) if message_id else True


def delete_message(message_id: int) -> bool:
    """Delete a previously posted message."""
    channel = _channel()
    if not channel or not message_id:
        return False
    body = _post("deleteMessage", {"chat_id": channel, "message_id": int(message_id)},
                 timeout=10)
    if body is not None:
        logger.info("Telegram message %d deleted", message_id)
        return True
    return False


def delete_last_message_for_website(website: str, message_type: str | None = None) -> bool:
    """Delete the most recent post for a website — used to retract a false alert."""
    message_id = db.get_last_telegram_message(website, message_type)
    if not message_id:
        logger.warning("No stored message_id for %s (%s)", website, message_type)
        return False
    return delete_message(message_id)


def _record_message(website: str, message_id, message_type: str) -> None:
    """Store a posted message id so it can be retracted later."""
    if not isinstance(message_id, int):
        return
    try:
        db.ensure_telegram_messages_table()
        db.save_telegram_message(website, message_id, message_type, _channel())
    except Exception as e:
        logger.debug("could not record telegram message for %s: %s", website, e)


def _deadline_value(conference: dict, field: str):
    """Read a deadline that may be a bare date or a {date, context} object."""
    entry = conference.get(field)
    return entry.get("date") if isinstance(entry, dict) else entry


def _build_conference_message(conference: dict) -> str:
    """Compose the 'new conference' channel post."""
    title = conference.get("title") or "Unknown Conference"
    city = conference.get("city") or "TBA"
    organizer = conference.get("organizer") or "TBA"
    category = conference.get("category") or "Other"
    website = conference.get("website") or ""
    description = conference.get("description")

    date_start = _format_date(conference.get("date_start"))
    date_end = _format_date(conference.get("date_end"))
    if not conference.get("date_end") or date_start == date_end:
        date_line = f"📅 {escape_html(date_start)}"
    else:
        date_line = f"📅 {escape_html(date_start)} to {escape_html(date_end)}"

    lines = [date_line]
    for field, label in _DEADLINE_LABELS:
        value = _deadline_value(conference, field)
        if value:
            lines.append(f"⏰ {label}: {escape_html(_format_date(value))}")

    short_title = title.split(",")[0].split("(")[0].split(":")[0].strip()
    tags = " ".join(f"#{tag}" for tag in (
        _make_hashtag(short_title)[:30],
        _make_hashtag(category),
        _make_hashtag(city),
        f"Bangladesh{datetime.now().year}",
    ) if tag)

    parts = [
        "🔔 New International Conference — Bangladesh",
        "",
        f"📌 {escape_html(title)}",
        "",
        "\n".join(lines),
        f"📍 {escape_html(city)}, Bangladesh",
        f"🏛 Organized by: {escape_html(organizer)}",
        f"🏷 Category: {escape_html(category)}",
    ]
    if description:
        # The overview is capped at 200 words upstream; keep the post readable.
        parts += ["", f"<i>{escape_html(str(description)[:400])}</i>"]
    parts += ["", f"🔗 {escape_html(website)}", "", tags]
    return "\n".join(parts)


def notify(conference: dict) -> bool:
    """Announce a conference on the channel. Returns True when sent."""
    message_id = send_plain_message(_build_conference_message(conference))
    if not message_id:
        return False
    _record_message(conference.get("website") or "", message_id, "conference")
    logger.info("Notification sent for: %s (msg_id=%s)", conference.get("title"), message_id)
    return True


# ── Pending notification flush ────────────────────────────────────────────────

def _pending_query() -> str:
    """Conferences saved but not yet announced, with a deadline in the window.

    Only the named deadline columns are consulted: the legacy
    `submission_deadline*` pair was backfilled by migration_011 and is no longer
    written or read anywhere.
    """
    deadline_cols = ", ".join(deadline_select_columns())
    window = " OR ".join(
        f"({typ}_deadline IS NOT NULL "
        f"AND {typ}_deadline >= CURRENT_DATE "
        f"AND {typ}_deadline <= CURRENT_DATE + INTERVAL '{NOTIFY_WINDOW_DAYS} days')"
        for typ in SUBMISSION_TYPES
    )
    return f"""
        SELECT id, title, date_start, date_end, city, website,
               organizer, category, description, {deadline_cols}
        FROM conferences
        WHERE is_notified = FALSE
          AND (date_start IS NULL OR date_start >= CURRENT_DATE)
          AND ({window})
        ORDER BY created_at ASC
    """


def _row_to_conference(row) -> tuple[int, dict]:
    """Map a pending-notification row to the dict `notify()` expects."""
    conference = {
        "title": row[1],
        "date_start": row[2],
        "date_end": row[3],
        "city": row[4],
        "website": row[5],
        "organizer": row[6],
        "category": row[7],
        "description": row[8],
    }
    offset = 9
    for i, typ in enumerate(SUBMISSION_TYPES):
        conference[f"{typ}_deadline"] = row[offset + i * 2]
        conference[f"{typ}_deadline_label"] = row[offset + i * 2 + 1]
    return row[0], conference


def notify_pending(notify_fn=notify) -> int:
    """Announce every conference still flagged `is_notified = FALSE`.

    Runs at the end of each scraper run and catches conferences saved when a
    previous notification attempt failed. Returns the number sent.
    """
    marked = db.mark_past_conferences_notified()
    if marked:
        logger.info("notify_pending: marked %d past conference(s) as notified", marked)

    try:
        with db.db_cursor() as cur:
            cur.execute(_pending_query())
            rows = cur.fetchall()
    except Exception as e:
        logger.error("notify_pending: error fetching pending conferences: %s", e)
        return 0

    if not rows:
        logger.info("notify_pending: no unnotified conferences found")
        return 0

    logger.info("notify_pending: found %d conference(s) to notify", len(rows))
    sent = 0
    for row in rows:
        conf_id, conference = _row_to_conference(row)
        try:
            delivered = notify_fn(conference)
        except Exception as e:
            logger.error("notify_pending: notify_fn raised for id=%s (%s): %s",
                         conf_id, conference.get("website"), e)
            delivered = False

        if not delivered:
            logger.warning("notify_pending: send failed for id=%s (%s) — retry next run",
                           conf_id, conference.get("website"))
            continue

        if db.mark_notified_with_retry(conf_id):
            sent += 1
            logger.info("notify_pending: notified id=%s — %s", conf_id, conference.get("title"))
        time.sleep(INTER_MESSAGE_SLEEP)

    return sent


# ── Deadline change alerts ────────────────────────────────────────────────────

def send_deadline_change_notification(title, website, changes) -> None:
    """Announce that a deadline moved.

    `changes` is a list of {"old", "new", "label"}. Entries without an old value
    are first-time discoveries, not changes, and are skipped.
    """
    lines = []
    for change in changes:
        if not change.get("old"):
            logger.warning("deadline_verification: skipping %s — no previous deadline", title)
            continue
        old_str = change["old"].strftime("%b %d")
        new_str = change["new"].strftime("%b %d") if change.get("new") else "Unknown"
        label = change.get("label") or ""
        prefix = f"{escape_html(label)}: " if label else "  "
        lines.append(f"{prefix}<s>{old_str}</s> → <b>{new_str}</b> 📝 <i>Updated</i>")

    if not lines:
        return

    message = (
        f"📢 <b>Deadline Updated</b>\n\n"
        f"<b>{escape_html(title)}</b>\n\n"
        f"{chr(10).join(lines)}\n\n"
        f"🔗 <a href=\"{escape_html(website)}\">{escape_html(website)}</a>"
    )

    message_id = send_plain_message(message)
    if message_id:
        _record_message(website, message_id, "deadline_change")
        logger.info("deadline_verification: sent change notification for %s (msg_id=%s)",
                    title, message_id)
