"""Telegram message construction and delivery.

Two responsibilities:
- notify():      push a newly discovered conference to the channel
- notify_pending(): flush any unnotified conferences (backlog + current run)
- send_deadline_change_notification(): alert on verified deadline changes
"""

import logging
import os
import re
import time
from datetime import datetime

import requests

from scraper import db
from scraper.schema import SUBMISSION_TYPES
from scraper.utils import escape_html, resolve_channel

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{}/sendMessage"

NOTIFY_WINDOW_DAYS = 30


def _make_hashtag(text):
    """Convert a string to a clean PascalCase hashtag."""
    words = re.sub(r"[^a-zA-Z0-9\s]", "", text).split()
    return "".join(w.capitalize() for w in words if w)


def _format_date(date_str):
    """Format a YYYY-MM-DD string into a human-readable date."""
    if not date_str:
        return "TBA"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%B %d, %Y")
    except (ValueError, TypeError):
        return date_str


def _send_message(
    text: str,
    *,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
) -> int | bool:
    """Post a message to the configured Telegram channel.

    Returns message_id (int) on success, False on failure.
    Returned int is truthy, so `if _send_message(...):` still works.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel = resolve_channel(
        os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
    )

    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return False
    if not channel:
        logger.error("TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK not set")
        return False

    payload = {"chat_id": channel, "text": text, "parse_mode": parse_mode}
    if disable_web_page_preview:
        payload["disable_web_page_preview"] = True

    try:
        resp = requests.post(TELEGRAM_API.format(token), json=payload, timeout=15)
    except requests.RequestException as e:
        logger.error("Telegram request error: %s", e)
        return False

    if resp.status_code == 200:
        try:
            data = resp.json()
            msg_id = data.get("result", {}).get("message_id")
            if msg_id:
                return int(msg_id)
        except Exception:
            pass
        return True
    logger.error("Telegram send failed (%d): %s", resp.status_code, resp.text)
    return False


def delete_message(message_id: int) -> bool:
    """Delete a Telegram message by its message_id. Returns True on success."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel = resolve_channel(
        os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
    )
    if not token or not channel or not message_id:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/deleteMessage",
            json={"chat_id": channel, "message_id": int(message_id)},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Telegram message %d deleted", message_id)
            return True
        logger.warning("Telegram delete failed (%d): %s", resp.status_code, resp.text)
        return False
    except requests.RequestException as e:
        logger.error("Telegram delete error for %d: %s", message_id, e)
        return False


def delete_last_message_for_website(website: str, message_type: str | None = None) -> bool:
    """Auto-delete the last notification for a website (for false alerts)."""
    msg_id = db.get_last_telegram_message(website, message_type)
    if not msg_id:
        logger.warning("No stored message_id for %s (%s)", website, message_type)
        return False
    return delete_message(msg_id)


def notify(conference):
    """Send a conference notification to the Telegram channel.

    Args:
        conference: Dict with keys: title, date_start, date_end, city,
                    organizer, category, website, confidence.

    Returns:
        True if sent successfully, False otherwise.
    """
    title = conference.get("title", "Unknown Conference")
    date_start = _format_date(conference.get("date_start"))
    date_end = _format_date(conference.get("date_end"))
    city = conference.get("city", "TBA")
    organizer = conference.get("organizer", "TBA")
    category = conference.get("category", "Other")
    website = conference.get("website", "")

    if date_start == date_end or not conference.get("date_end"):
        date_line = f"📅 {escape_html(date_start)}"
    else:
        date_line = f"📅 {escape_html(date_start)} to {escape_html(date_end)}"

    # Submission deadlines only — other types are stored but not announced
    deadline_lines = []
    for field, label in [
        ("abstract_deadline", "Abstract"),
        ("full_paper_deadline", "Full paper"),
    ]:
        entry = conference.get(field)
        date_val = entry.get("date") if isinstance(entry, dict) else entry
        if date_val:
            deadline_lines.append(f"⏰ {label}: {_format_date(date_val)}")
    if deadline_lines:
        date_block = date_line + "\n" + "\n".join(deadline_lines)
    else:
        date_block = date_line

    short_title = title.split(",")[0].split("(")[0].split(":")[0].strip()
    title_tag = _make_hashtag(short_title)[:30]
    cat_tag = _make_hashtag(category)
    city_tag = _make_hashtag(city)
    year = datetime.now().year
    country_tag = f"Bangladesh{year}"

    message = (
        f"\U0001F514 New International Conference \u2014 Bangladesh\n\n"
        f"\U0001F4CC {escape_html(title)}\n\n"
        f"{date_block}\n"
        f"\U0001F4CD {escape_html(city)}, Bangladesh\n"
        f"\U0001F3DB Organized by: {escape_html(organizer)}\n"
        f"\U0001F3F7 Category: {escape_html(category)}\n\n"
        f"\U0001F517 {escape_html(website)}\n\n"
        f"#{title_tag} #{cat_tag} #{city_tag} #{country_tag}"
    )

    msg_id = _send_message(message)
    if msg_id:
        try:
            db.ensure_telegram_messages_table()
            channel = resolve_channel(
                os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
            )
            if isinstance(msg_id, int):
                db.save_telegram_message(website, msg_id, "conference", channel)
        except Exception:
            pass
        logger.info("Notification sent for: %s (msg_id=%s)", title, msg_id)
        return True
    return False


# ── Pending notification flush ──


def _mark_past_conferences_notified() -> None:
    """Mark conferences that already started as notified (cleanup from before date filter)."""
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE conferences SET is_notified = TRUE, notified_at = NOW() "
            "WHERE is_notified = FALSE AND date_start < CURRENT_DATE"
        )
        if cur.rowcount > 0:
            logger.info("notify_pending: marked %d past conferences as notified", cur.rowcount)
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("notify_pending: cleanup error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def notify_pending(notify_fn) -> int:
    """
    Send Telegram notifications for all conferences where is_notified = FALSE.

    Opens a fresh DB connection per operation to avoid Neon idle timeout.
    Returns the count of successfully notified conferences.

    This runs at the end of every scraper run and catches:
    - Conferences saved in a previous run where notification crashed
    - Conferences saved in the current run's Phase 4 loop
    - Any backlog that accumulated during debugging/development
    """
    _mark_past_conferences_notified()

    # Submission deadlines only
    select_dl = ", ".join(f"{typ}_deadline, {typ}_deadline_label" for typ in SUBMISSION_TYPES)
    sub_checks = " OR ".join(
        f"({typ}_deadline IS NOT NULL"
        f" AND {typ}_deadline >= CURRENT_DATE"
        f" AND {typ}_deadline <= CURRENT_DATE + INTERVAL '{NOTIFY_WINDOW_DAYS} days')"
        for typ in SUBMISSION_TYPES
    )
    legacy_checks = " OR ".join(
        f"({col} IS NOT NULL"
        f" AND {col} >= CURRENT_DATE"
        f" AND {col} <= CURRENT_DATE + INTERVAL '{NOTIFY_WINDOW_DAYS} days')"
        for col in ("submission_deadline", "submission_deadline_2")
    )
    date_or_clause = f"({sub_checks} OR {legacy_checks})" if sub_checks else f"({legacy_checks})"

    notified_count = 0
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, title, date_start, date_end, city, website,
                   organizer, category, confidence,
                   {select_dl}
            FROM conferences
            WHERE is_notified = FALSE
              AND (date_start IS NULL OR date_start >= CURRENT_DATE)
              AND ({date_or_clause})
            ORDER BY created_at ASC
            """
        )
        pending = cur.fetchall()
        cur.close()
        conn.close()
        conn = None

        if not pending:
            logger.info("notify_pending: no unnotified conferences found")
            return 0

        logger.info(
            "notify_pending: found %d conference(s) to notify", len(pending)
        )

        for row in pending:
            conf_id = row[0]
            conf = {
                "title":      row[1],
                "date_start": str(row[2]) if row[2] else None,
                "date_end":   str(row[3]) if row[3] else None,
                "city":       row[4],
                "website":    row[5],
                "organizer":  row[6],
                "category":   row[7],
                "confidence": row[8],
            }
            # Submission deadlines only
            dl_offset = 9
            for i, typ in enumerate(SUBMISSION_TYPES):
                date_col_idx = dl_offset + i * 2
                label_col_idx = dl_offset + i * 2 + 1
                conf[f"{typ}_deadline"] = str(row[date_col_idx]) if row[date_col_idx] else None
                conf[f"{typ}_deadline_label"] = row[label_col_idx]

            try:
                success = notify_fn(conf)
            except Exception as e:
                logger.error(
                    "notify_pending: notify_fn raised for id=%d (%s): %s",
                    conf_id, conf.get("website"), e
                )
                success = False

            if success:
                if db.mark_notified_with_retry(conf_id):
                    notified_count += 1
                    logger.info(
                        "notify_pending: notified id=%d — %s",
                        conf_id, conf.get("title")
                    )
                time.sleep(2)  # avoid burst spam
            else:
                logger.warning(
                    "notify_pending: notify_fn returned False for id=%d (%s), "
                    "will retry next run",
                    conf_id, conf.get("website")
                )

    except Exception as e:
        logger.error("notify_pending: error fetching pending conferences: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return notified_count


# ── Deadline change alerts (from verification) ──


def send_deadline_change_notification(title, website, changes) -> None:
    """Send a Telegram notification that a deadline has changed.

    Args:
        title: Conference title.
        website: Conference website URL.
        changes: List of {"old": date, "new": date, "label": str} dicts.
    """
    lines = []
    for change in changes:
        # Skip if old value is None — this is first-time discovery, not an update
        if not change["old"]:
            logger.warning(
                "deadline_verification: skipping notification for %s — old deadline is None",
                title
            )
            continue
        old_str = change["old"].strftime("%b %d")
        new_str = change["new"].strftime("%b %d") if change["new"] else "Unknown"
        lines.append(
            f"  <s>{old_str}</s> → <b>{new_str}</b> 📝 <i>Updated</i>"
        )

    if not lines:
        return

    updates_block = "\n".join(lines)

    message = (
        f"📢 <b>Deadline Updated</b>\n\n"
        f"<b>{escape_html(title)}</b>\n\n"
        f"{updates_block}\n\n"
        f"🔗 <a href=\"{escape_html(website)}\">{escape_html(website)}</a>"
    )

    msg_id = _send_message(message)
    if msg_id:
        try:
            db.ensure_telegram_messages_table()
            channel = resolve_channel(
                os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
            )
            if isinstance(msg_id, int):
                db.save_telegram_message(website, msg_id, "deadline_change", channel)
        except Exception:
            pass
        logger.info(
            "deadline_verification: sent change notification for %s (msg_id=%s)", title, msg_id
        )
