import logging
import os
import re
from datetime import datetime

import requests

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
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
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
