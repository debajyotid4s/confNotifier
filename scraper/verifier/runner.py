import logging

from scraper import db

from .guard import _should_run_verification
from .process import _process_conference
from .queries import _load_conferences_for_verification

logger = logging.getLogger(__name__)


def verify_deadlines(playwright) -> None:
    """Re-extract deadlines for upcoming conferences and announce any change."""
    if not _should_run_verification():
        return
    logger.info("deadline_verification: starting deadline re-check")
    rows = _load_conferences_for_verification()
    if rows is None:
        return
    if not rows:
        logger.info("deadline_verification: no upcoming conferences to check")
        db.mark_verification_done()
        return
    logger.info("deadline_verification: checking %d conference(s)", len(rows))
    for row in rows:
        try:
            _process_conference(row, playwright)
        except Exception as e:
            logger.error("deadline_verification: error processing %s: %s", row[2], e)
    db.mark_verification_done()
    logger.info("deadline_verification: complete")
