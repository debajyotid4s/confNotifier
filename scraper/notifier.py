import logging
import os
import re
from datetime import datetime, date

import requests

from db import get_connection

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{}/sendMessage"


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


def notify(conference):
    """Send a conference notification to the Telegram channel.

    Args:
        conference: Dict with keys: title, date_start, date_end, city,
                    organizer, category, website, confidence.

    Returns:
        True if sent successfully, False otherwise.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")

    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return False
    if not channel_id:
        logger.error("TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK not set")
        return False

    url = TELEGRAM_API.format(token)

    # Auto-convert https://t.me/name → @name (Telegram API requires @id or numeric id)
    if channel_id.startswith("https://t.me/"):
        channel_id = "@" + channel_id.split("t.me/")[1].rstrip("/")
    elif channel_id.startswith("http://t.me/"):
        channel_id = "@" + channel_id.split("t.me/")[1].rstrip("/")

    if not channel_id:
        logger.error("No TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK set")
        return False

    title = conference.get("title", "Unknown Conference")
    date_start = _format_date(conference.get("date_start"))
    date_end = _format_date(conference.get("date_end"))
    city = conference.get("city", "TBA")
    organizer = conference.get("organizer", "TBA")
    category = conference.get("category", "Other")
    website = conference.get("website", "")

    if date_start == date_end or not conference.get("date_end"):
        date_line = f"📅 {date_start}"
    else:
        date_line = f"📅 {date_start} to {date_end}"

    short_title = title.split(",")[0].split("(")[0].split(":")[0].strip()
    title_tag = _make_hashtag(short_title)[:30]
    cat_tag = _make_hashtag(category)
    city_tag = _make_hashtag(city)
    year = datetime.now().year
    country_tag = f"Bangladesh{year}"

    message = (
        f"\U0001F514 New International Conference \u2014 Bangladesh\n\n"
        f"\U0001F4CC {title}\n\n"
        f"{date_line}\n"
        f"\U0001F4CD {city}, Bangladesh\n"
        f"\U0001F3DB Organized by: {organizer}\n"
        f"\U0001F3F7 Category: {category}\n\n"
        f"\U0001F517 {website}\n\n"
        f"#{title_tag} #{cat_tag} #{city_tag} #{country_tag}"
    )

    try:
        resp = requests.post(
            url,
            json={"chat_id": channel_id, "text": message},
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("Notification sent for: %s", title)
            return True
        else:
            logger.error(
                "Telegram send failed (%d): %s",
                resp.status_code, resp.text,
            )
            return False
    except requests.RequestException as e:
        logger.error("Telegram request error: %s", e)
        return False


def send_deadline_reminder() -> int:
    """Send daily paper submission deadline reminder to the Telegram channel.

    Queries conferences with upcoming submission deadlines (today through 30 days).
    Sends a single grouped message. Returns 1 if sent, 0 if no deadlines found.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")

    if not token or not channel_id:
        logger.error("deadline_reminder: missing TELEGRAM_BOT_TOKEN or channel ID")
        return 0

    # Auto-convert https://t.me/name → @name
    if channel_id.startswith("https://t.me/"):
        channel_id = "@" + channel_id.split("t.me/")[1].rstrip("/")
    elif channel_id.startswith("http://t.me/"):
        channel_id = "@" + channel_id.split("t.me/")[1].rstrip("/")

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT title, submission_deadline, website, city
            FROM conferences
            WHERE submission_deadline IS NOT NULL
              AND submission_deadline >= CURRENT_DATE
              AND submission_deadline <= CURRENT_DATE + INTERVAL '30 days'
              AND is_notified = TRUE
            ORDER BY submission_deadline ASC
            """
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        logger.error("deadline_reminder: DB query error: %s", e)
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    if not rows:
        logger.info("deadline_reminder: no upcoming deadlines found")
        return 0

    today = date.today()
    lines = []
    for title, deadline, website, city in rows:
        days_left = (deadline - today).days
        if days_left == 0:
            countdown = "today"
        elif days_left == 1:
            countdown = "tomorrow"
        else:
            countdown = f"in {days_left} days"
        deadline_fmt = _format_date(str(deadline))
        short_title = title.split(",")[0].split("(")[0].split(":")[0].strip()
        lines.append(f"📌 {short_title}\n   Deadline: {deadline_fmt} ({countdown})\n   🔗 {website}")

    year = datetime.now().year
    message = (
        f"📚 Paper Submission Deadline Reminder\n\n"
        f"My Dear Research Enthusiasts,\n\n"
        f"Here are the upcoming paper submission deadlines:\n\n"
        + "\n\n".join(lines)
        + f"\n\nDon't miss out! Plan your submissions accordingly.\n\n"
        f"#Bangladesh{year} #CallForPapers"
    )

    try:
        resp = requests.post(
            TELEGRAM_API.format(token),
            json={"chat_id": channel_id, "text": message},
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("deadline_reminder: sent successfully (%d conferences)", len(rows))
            return 1
        else:
            logger.error("deadline_reminder: Telegram send failed (%d): %s", resp.status_code, resp.text)
            return 0
    except requests.RequestException as e:
        logger.error("deadline_reminder: Telegram request error: %s", e)
        return 0
