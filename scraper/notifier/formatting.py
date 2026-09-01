import re
from datetime import datetime

from scraper.utils import escape_html

from .config import _DEADLINE_LABELS


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
        parts += ["", f"<i>{escape_html(str(description)[:400])}</i>"]
    parts += ["", f"🔗 {escape_html(website)}", "", tags]
    return "\n".join(parts)
