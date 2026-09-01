"""Date coercion and plausibility."""

import re
from datetime import date, datetime

#: How far outside "now" a conference date may plausibly fall. A CFP for an
#: event more than this far out is almost always a mis-parse; anything in the
#: past is a stale edition.
MAX_YEARS_AHEAD = 4
MAX_YEARS_BEHIND = 1

_NON_DATES = frozenset({
    "", "tba", "tbd", "n/a", "na", "none", "null", "unknown",
    "to be announced", "to be decided", "not announced", "coming soon",
})

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

#: "August 15, 2027" / "15 August 2027" — accepted because the model
#: occasionally echoes the page wording instead of emitting ISO.
_TEXT_DATE_RE = re.compile(
    r"(?:(?P<month1>[a-z]+)\.?\s+(?P<day1>\d{1,2})|(?P<day2>\d{1,2})\s+(?P<month2>[a-z]+)\.?)"
    r"[,\s]+(?P<year>(?:19|20)\d{2})",
    re.IGNORECASE,
)

def coerce_date(value) -> date | None:
    """Parse a model-supplied date into a real `date`, or None.

    Accepts an ISO string, a `date`/`datetime`, or common written forms.
    Returns None for placeholders ("TBA"), impossible calendar dates
    ("2027-02-30") and anything unrecognised — never raises.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower() in _NON_DATES:
        return None
    iso = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if iso:
        return _build_date(*(int(g) for g in iso.groups()))
    slash = re.match(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$", text)
    if slash:
        day, month, year = (int(g) for g in slash.groups())
        # Ambiguous DD/MM vs MM/DD: prefer DD/MM (Bangladeshi convention) and
        # fall back to MM/DD when the first field cannot be a day.
        built = _build_date(year, month, day)
        return built or _build_date(year, day, month)
    match = _TEXT_DATE_RE.search(text)
    if match:
        month_name = (match.group("month1") or match.group("month2") or "").lower()
        day = int(match.group("day1") or match.group("day2"))
        month = _MONTHS.get(month_name)
        if month:
            return _build_date(int(match.group("year")), month, day)
    return None


def _build_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def is_plausible_date(value: date, now: date | None = None) -> bool:
    """True when a date is close enough to now to be a live conference date."""
    today = now or date.today()
    return (today.year - MAX_YEARS_BEHIND) <= value.year <= (today.year + MAX_YEARS_AHEAD)
