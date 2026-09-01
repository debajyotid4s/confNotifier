"""scraper/reminders/queries.py — fetch upcoming deadlines."""

from scraper import db
from scraper.reminders.constants import WINDOW_DAYS
from scraper.reminders.formatting import _within_window
from scraper.schema import SUBMISSION_TYPES, deadline_range_checks


def _fetch_entries() -> list[tuple]:
    """Every upcoming deadline as (deadline, website, title, previous_deadline)."""
    columns = []
    for typ in SUBMISSION_TYPES:
        columns += [f"{typ}_deadline", f"{typ}_deadline_previous"]
    window = " OR ".join(deadline_range_checks(WINDOW_DAYS))

    with db.db_cursor() as cur:
        cur.execute(f"""
            SELECT title, website, {", ".join(columns)}
            FROM conferences
            WHERE {window}
        """)
        rows = cur.fetchall()

    entries = []
    for row in rows:
        title, website = row[0], row[1]
        for i, _typ in enumerate(SUBMISSION_TYPES):
            deadline = row[2 + i * 2]
            previous = row[2 + i * 2 + 1]
            if not _within_window(deadline):
                continue
            changed = previous is not None and previous != deadline
            entries.append((deadline, website, title, previous if changed else None))
    return entries
