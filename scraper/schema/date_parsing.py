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

#: Bare month-day without a year ("August 28") — resolved against the single
#: distinct year in the same text, skipped when the year is ambiguous.
_MONTH_DAY_RE = re.compile(r"\b([a-z]+)\.?\s+(\d{1,2})\b", re.IGNORECASE)

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")

_SLASH_DATE_RE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")

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


def find_dates(text) -> list[date]:
    """Every parseable calendar date in free text, deduped and sorted.

    Finds ISO, written-with-year ("September 11, 2026"), and slash dates,
    plus yearless month-day pairs ("August 28") resolved against the single
    distinct year in the same text — skipped when the year is ambiguous or
    absent. Impossible calendar dates are dropped. Never raises.
    """
    if not text or not isinstance(text, str):
        return []
    found: list[date] = []
    consumed: list[tuple[int, int]] = []

    def _overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in consumed)

    for match in _ISO_DATE_RE.finditer(text):
        built = _build_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if built:
            found.append(built)
            consumed.append(match.span())
    for match in _SLASH_DATE_RE.finditer(text):
        if _overlaps(match.span()):
            continue
        day, month, year = (int(g) for g in match.groups())
        # Same convention as coerce_date: prefer DD/MM, fall back to MM/DD.
        built = _build_date(year, month, day) or _build_date(year, day, month)
        if built:
            found.append(built)
            consumed.append(match.span())
    for match in _TEXT_DATE_RE.finditer(text):
        if _overlaps(match.span()):
            continue
        month = _MONTHS.get((match.group("month1") or match.group("month2") or "").lower())
        day = int(match.group("day1") or match.group("day2"))
        if month:
            built = _build_date(int(match.group("year")), month, day)
            if built:
                found.append(built)
                consumed.append(match.span())
    years = {d.year for d in found}
    if len(years) == 1:
        (only_year,) = years
        for match in _MONTH_DAY_RE.finditer(text):
            if _overlaps(match.span()):
                continue
            month = _MONTHS.get(match.group(1).lower())
            day = int(match.group(2))
            if month and 1 <= day <= 31:
                built = _build_date(only_year, month, day)
                if built and built not in found:
                    found.append(built)
    return sorted(set(found))


def is_plausible_date(value: date, now: date | None = None) -> bool:
    """True when a date is close enough to now to be a live conference date."""
    today = now or date.today()
    return (today.year - MAX_YEARS_BEHIND) <= value.year <= (today.year + MAX_YEARS_AHEAD)
