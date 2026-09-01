"""Edition identity."""

from datetime import date, datetime

from .title import title_key


def _year_of(value) -> int | None:
    if isinstance(value, (date, datetime)):
        return value.year
    if isinstance(value, str) and len(value) >= 4:
        head = value[:4]
        if head.isdigit():
            year = int(head)
            if 1900 <= year <= 2200:
                return year
    return None


def edition_year(
    title: str | None = None,
    date_start=None,
    website: str | None = None,
    deadlines: list | None = None,
) -> int | None:
    """Best guess of which edition (year) a conference record refers to.

    Priority: explicit conference start date > earliest submission deadline >
    year in the title > year in the URL. Returns None when nothing is known
    (a genuinely TBA record).
    """
    year = _year_of(date_start)
    if year:
        return year
    for deadline in sorted(
        (d for d in (deadlines or []) if d is not None),
        key=lambda d: str(d),
    ):
        year = _year_of(deadline)
        if year:
            return year
    from scraper.patterns import years_in  # local import: avoids a cycle

    for source in (title, website):
        found = years_in(source or "")
        if found:
            return max(found)
    return None


def edition_key(
    title: str | None,
    date_start=None,
    website: str | None = None,
    deadlines: list | None = None,
) -> str | None:
    """Stable identity for one edition of one conference, or None if unknowable.

    Two records sharing an edition_key are the same conference edition even when
    their URLs differ. None means "cannot decide" — the caller must fall back to
    URL comparison rather than risk merging unrelated records.
    """
    key = title_key(title or "")
    if not key:
        return None
    year = edition_year(title, date_start, website, deadlines)
    if year is None:
        return None
    return f"{key}:{year}"
