from scraper.schema import SUBMISSION_TYPES, deadline_select_columns

from .config import NOTIFY_WINDOW_DAYS


def _pending_query() -> str:
    """Conferences saved but not yet announced, with a deadline in the window.

    Only the named deadline columns are consulted: the legacy
    `submission_deadline*` pair was backfilled by migration_011 and is no longer
    written or read anywhere.
    """
    deadline_cols = ", ".join(deadline_select_columns())
    window = " OR ".join(
        f"({typ}_deadline IS NOT NULL "
        f"AND {typ}_deadline >= CURRENT_DATE "
        f"AND {typ}_deadline <= CURRENT_DATE + INTERVAL '{NOTIFY_WINDOW_DAYS} days')"
        for typ in SUBMISSION_TYPES
    )
    return f"""
        SELECT id, title, date_start, date_end, city, website,
               organizer, category, description, {deadline_cols}
        FROM conferences
        WHERE is_notified = FALSE
          AND (date_start IS NULL OR date_start >= CURRENT_DATE)
          AND ({window})
        ORDER BY created_at ASC
    """
