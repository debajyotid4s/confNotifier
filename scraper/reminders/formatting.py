"""scraper/reminders/formatting.py — urgency and progress helpers."""

from datetime import date

from scraper.reminders.constants import BAR_LEN, SOON_DAYS, URGENT_DAYS, WINDOW_DAYS


def _urgency_emoji(days_left: int) -> str:
    if days_left <= URGENT_DAYS:
        return "🔥"
    if days_left <= SOON_DAYS:
        return "⏳"
    return "✅"


def _elapsed_pct(days_left: int) -> int:
    """How much of the 30-day window has passed, clamped to 0-100."""
    return max(0, min(100, round(100 - (days_left / WINDOW_DAYS) * 100)))


def _progress_bar(pct: int) -> str:
    filled = round(pct / 100 * BAR_LEN)
    return f"[{'█' * filled}{'░' * (BAR_LEN - filled)}]"


def _within_window(value) -> bool:
    return value is not None and 0 <= (value - date.today()).days <= WINDOW_DAYS
