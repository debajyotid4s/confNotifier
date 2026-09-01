import logging
import time

from scraper import db
from scraper.schema import SUBMISSION_TYPES

from .conference import notify
from .config import INTER_MESSAGE_SLEEP
from .pending_query import _pending_query

logger = logging.getLogger(__name__)


def _row_to_conference(row) -> tuple[int, dict]:
    """Map a pending-notification row to the dict `notify()` expects."""
    conference = {
        "title": row[1],
        "date_start": row[2],
        "date_end": row[3],
        "city": row[4],
        "website": row[5],
        "organizer": row[6],
        "category": row[7],
        "description": row[8],
    }
    offset = 9
    for i, typ in enumerate(SUBMISSION_TYPES):
        conference[f"{typ}_deadline"] = row[offset + i * 2]
        conference[f"{typ}_deadline_label"] = row[offset + i * 2 + 1]
    return row[0], conference


def notify_pending(notify_fn=notify) -> int:
    """Announce every conference still flagged `is_notified = FALSE`.

    Runs at the end of each scraper run and catches conferences saved when a
    previous notification attempt failed. Returns the number sent.
    """
    marked = db.mark_past_conferences_notified()
    if marked:
        logger.info("notify_pending: marked %d past conference(s) as notified", marked)
    try:
        with db.db_cursor() as cur:
            cur.execute(_pending_query())
            rows = cur.fetchall()
    except Exception as e:
        logger.error("notify_pending: error fetching pending conferences: %s", e)
        return 0
    if not rows:
        logger.info("notify_pending: no unnotified conferences found")
        return 0
    logger.info("notify_pending: found %d conference(s) to notify", len(rows))
    sent = 0
    for row in rows:
        conf_id, conference = _row_to_conference(row)
        try:
            delivered = notify_fn(conference)
        except Exception as e:
            logger.error("notify_pending: notify_fn raised for id=%s (%s): %s",
                         conf_id, conference.get("website"), e)
            delivered = False
        if not delivered:
            logger.warning("notify_pending: send failed for id=%s (%s) — retry next run",
                           conf_id, conference.get("website"))
            continue
        if db.mark_notified_with_retry(conf_id):
            sent += 1
            logger.info("notify_pending: notified id=%s — %s", conf_id, conference.get("title"))
        time.sleep(INTER_MESSAGE_SLEEP)
    return sent
