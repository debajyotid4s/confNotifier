import logging

from scraper import db
from scraper.schema import DEADLINE_TYPES, deadline_range_checks, deadline_select_columns

from .constants import VERIFY_WINDOW_DAYS, _DL_OFFSET

logger = logging.getLogger(__name__)


def _load_conferences_for_verification() -> list | None:
    """Upcoming conferences with a deadline inside the verify window.

    Returns None on a DB error so the caller can skip the run instead of
    stamping it as done.
    """
    select_dl = ", ".join(deadline_select_columns())
    window = " OR ".join(deadline_range_checks(VERIFY_WINDOW_DAYS, past_days=VERIFY_WINDOW_DAYS))
    try:
        with db.db_cursor() as cur:
            cur.execute(f"""
                SELECT id, title, website, raw_source, {select_dl}
                FROM conferences
                WHERE date_start > CURRENT_DATE
                  AND ({window})
                ORDER BY date_start ASC
            """)
            return cur.fetchall()
    except Exception as e:
        logger.error("deadline_verification: failed to load conferences: %s", e)
        return None


def _stored_deadlines(row) -> dict:
    """Map a verification row to {type: {date, label}}."""
    return {
        typ: {
            "date": row[_DL_OFFSET + i * 2],
            "label": row[_DL_OFFSET + i * 2 + 1],
        }
        for i, typ in enumerate(DEADLINE_TYPES)
    }
