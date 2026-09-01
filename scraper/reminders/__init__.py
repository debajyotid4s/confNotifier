"""scraper/reminders — package facade."""

from scraper.reminders.constants import BAR_LEN, SOON_DAYS, URGENT_DAYS, WINDOW_DAYS  # noqa: F401
from scraper.reminders.formatting import (  # noqa: F401
    _elapsed_pct,
    _progress_bar,
    _urgency_emoji,
    _within_window,
)
from scraper.reminders.queries import _fetch_entries  # noqa: F401
from scraper.reminders.render import _render  # noqa: F401
from scraper.reminders.runner import main, send_deadline_reminders  # noqa: F401

__all__ = [
    "WINDOW_DAYS", "BAR_LEN", "URGENT_DAYS", "SOON_DAYS",
    "_urgency_emoji", "_elapsed_pct", "_progress_bar", "_within_window",
    "_fetch_entries", "_render", "send_deadline_reminders", "main",
]
