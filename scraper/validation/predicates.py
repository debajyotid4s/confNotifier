from datetime import date

from scraper.schema import SUBMISSION_TYPES, coerce_date


def has_usable_content(conf: dict) -> bool:
    """True when an extraction carries at least one fact worth storing."""
    return bool(
        conf.get("date_start")
        or conf.get("date_end")
        or any(conf.get(f"{typ}_deadline") for typ in SUBMISSION_TYPES)
    )


def all_deadlines_past(conf: dict, now: date | None = None) -> bool:
    """True when every deadline present has already passed."""
    today = now or date.today()
    deadlines = [
        coerce_date(conf.get(f"{typ}_deadline"))
        for typ in SUBMISSION_TYPES
    ]
    present = [d for d in deadlines if d is not None]
    return bool(present) and all(d < today for d in present)
