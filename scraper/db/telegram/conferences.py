"""scraper/db/telegram/conferences.py — notify flags."""

import logging
import time

from scraper.db.connection import _safe, db_cursor

logger = logging.getLogger(__name__)


@_safe("mark_notified", default=False)
def mark_notified(conf_id: int) -> bool:
    """Flag a conference as announced so it is never posted twice."""
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE id = %s", (conf_id,))
    return True


def mark_notified_with_retry(conf_id: int, max_attempts: int = 3) -> bool:
    """Flag a conference as announced, retrying so a blip cannot cause a repost."""
    for attempt in range(max_attempts):
        if mark_notified(conf_id):
            return True
        logger.error("mark_notified attempt %d/%d failed for id=%s", attempt + 1, max_attempts, conf_id)
        time.sleep(2)
    logger.critical("mark_notified FAILED all %d attempts for id=%s — duplicate notification risk", max_attempts, conf_id)
    return False


@_safe("mark_past_conferences_notified", default=0)
def mark_past_conferences_notified() -> int:
    """Suppress announcements for conferences that already started."""
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE is_notified = FALSE AND date_start < CURRENT_DATE")
        return cur.rowcount
