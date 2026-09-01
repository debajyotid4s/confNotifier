"""Sanitize extracted date fields."""

from datetime import date

from .constants import DEADLINE_TYPES
from .date_parsing import _NON_DATES, coerce_date, is_plausible_date


def sanitize_dates(result: dict, now: date | None = None) -> tuple[dict, list[str]]:
    """Coerce every date field in place and drop the ones that make no sense.

    Rules applied, in order:
      1. unparseable / placeholder / implausible-year values become None
      2. `date_end` earlier than `date_start` is dropped
      3. a submission deadline after the conference *ends* is dropped —
         it is a post-conference date the model mislabelled
      4. `full_paper` earlier than `abstract` is left alone (legitimate on some
         sites) but reported, so validation can weigh it

    Returns (result, notes) where `notes` explains every value removed.
    """
    today = now or date.today()
    notes: list[str] = []

    def take(field: str) -> date | None:
        raw = result.get(field)
        if raw is None:
            return None
        parsed = coerce_date(raw)
        if parsed is None:
            if str(raw).strip().lower() not in _NON_DATES:
                notes.append(f"{field}: unparseable value {raw!r} dropped")
            return None
        if not is_plausible_date(parsed, today):
            notes.append(f"{field}: implausible year {parsed.isoformat()} dropped")
            return None
        return parsed

    start = take("date_start")
    end = take("date_end")
    if start and end and end < start:
        notes.append(f"date_end {end.isoformat()} precedes date_start {start.isoformat()} — dropped")
        end = None
    result["date_start"] = start.isoformat() if start else None
    result["date_end"] = end.isoformat() if end else None
    conference_end = end or start
    for typ in DEADLINE_TYPES:
        field = f"{typ}_deadline"
        deadline = take(field)
        if deadline and conference_end and deadline > conference_end:
            notes.append(
                f"{field}: {deadline.isoformat()} falls after the conference "
                f"({conference_end.isoformat()}) — dropped"
            )
            deadline = None
        result[field] = deadline.isoformat() if deadline else None
    abstract = coerce_date(result.get("abstract_deadline"))
    full_paper = coerce_date(result.get("full_paper_deadline"))
    if abstract and full_paper and full_paper < abstract:
        notes.append(
            f"full_paper_deadline {full_paper.isoformat()} precedes "
            f"abstract_deadline {abstract.isoformat()} — possible swap"
        )
    return result, notes
