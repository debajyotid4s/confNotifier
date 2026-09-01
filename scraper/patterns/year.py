"""Year window helpers."""

from __future__ import annotations

import re
from datetime import datetime

# Editions this many years back are still allowed: a conference announced in
# December 2026 for "ICXYZ 2026" is legitimately reachable in January 2027.
YEARS_BACK = 1
YEARS_AHEAD = 3

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def year_window(now: datetime | None = None) -> tuple[int, int]:
    """Inclusive [min, max] edition year currently considered live."""
    year = (now or datetime.now()).year
    return year - YEARS_BACK, year + YEARS_AHEAD


def years_in(text: str) -> list[int]:
    """All 4-digit year-like tokens in a string."""
    return [int(m) for m in _YEAR_RE.findall(text or "")]


def _year_verdict(text: str, now: datetime | None = None) -> str:
    """Classify the year tokens in `text`.

    Returns "live" (a year inside the window), "stale" (only years before the
    window) or "none" (no year tokens at all).
    """
    found = years_in(text)
    if not found:
        return "none"
    lo, hi = year_window(now)
    if any(lo <= y <= hi for y in found):
        return "live"
    if max(found) < lo:
        return "stale"
    # Only far-future years (typos like 2099) — treat as no signal.
    return "none"
