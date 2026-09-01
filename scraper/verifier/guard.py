import logging
from datetime import date, datetime, timezone

from scraper import db

from .constants import TASK_NAME, VERIFY_INTERVAL_HOURS

logger = logging.getLogger(__name__)


def _should_run_verification() -> bool:
    """True when the last run is older than VERIFY_INTERVAL_HOURS.

    Errors resolve to True: missing a verification is worse than doing one twice.
    """
    last_run = db.get_task_last_run(TASK_NAME)
    if not last_run:
        return True
    if isinstance(last_run, datetime):
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
    elif isinstance(last_run, date):
        last_run = datetime.combine(last_run, datetime.min.time(), tzinfo=timezone.utc)
    else:
        return True
    hours_since = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
    if hours_since < VERIFY_INTERVAL_HOURS:
        logger.info("deadline_verification: last ran %.1fh ago (< %dh), skipping",
                    hours_since, VERIFY_INTERVAL_HOURS)
        return False
    return True
