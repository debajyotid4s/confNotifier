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
from scraper.schema import DEADLINE_TYPES, deadline_range_checks, deadline_select_columns
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
) -> bool:
    """Post a message to the configured Telegram channel. Returns True on success."""
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
        return True
    logger.error("Telegram send failed (%d): %s", resp.status_code, resp.text)
    return False


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

    # Deadline fields are flat YYYY-MM-DD strings (post-normalization); a nested
    # {"date": ...} dict is also accepted defensively.
    deadline_lines = []
    for field, label in [
        ("abstract_deadline", "Abstract"),
        ("full_paper_deadline", "Full paper"),
        ("camera_ready_deadline", "Camera-ready"),
        ("registration_deadline", "Registration"),
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

    if _send_message(message):
        logger.info("Notification sent for: %s", title)
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

    select_dl = ", ".join(deadline_select_columns())
    date_or_clause = " OR ".join(
        deadline_range_checks(NOTIFY_WINDOW_DAYS, include_legacy=True)
    )

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
            # Deadline fields: date + label per type, in DEADLINE_TYPES order.
            dl_offset = 9
            for i, typ in enumerate(DEADLINE_TYPES):
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

    if _send_message(message):
        logger.info(
            "deadline_verification: sent change notification for %s", title
        )
