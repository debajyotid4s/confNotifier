"""scraper/pipeline/runner/persist.py — save and notify."""

import logging

from scraper import db
from scraper.dedup import ConferenceIndex
from scraper.notifier import notify
from scraper.pipeline.outcomes import NOTIFY_WINDOW_DAYS, Outcome
from scraper.pipeline.precheck import extracted_deadlines, has_deadline_within_days
from scraper.pipeline.stats import RunStats
from scraper.validation import has_usable_content

logger = logging.getLogger(__name__)


def _save_and_notify(url: str, result: dict, index: ConferenceIndex, existing_id: int | None, stats: RunStats) -> Outcome:
    """Persist a validated extraction and announce it when a deadline is near."""
    result["raw_source"] = url
    success, was_inserted, conf_id = db.save_conference(result, existing_id=existing_id)
    if not success:
        logger.error("Conference save failed for %s — will retry next run", url)
        return Outcome.FAILED_SAVE
    if conf_id:
        index.add(conf_id, result.get("website") or url, result.get("title"), result.get("date_start"), extracted_deadlines(result))
    if existing_id is not None:
        logger.info("Merged duplicate edition into conference %s: %s", existing_id, result.get("title"))
        stats.bump("merged")
        return Outcome.DUPLICATE_EDITION
    if not was_inserted:
        logger.info("Conference already in DB (deadlines refreshed): %s", result.get("title"))
        stats.bump("updated")
        return Outcome.UPDATED
    logger.info("New conference saved: %s", result.get("title"))
    stats.bump("inserted")
    try:
        from data_collection.collector import record_confirmed
        record_confirmed(url, source="scraper_daily", page_title=result.get("title"))
    except Exception:
        pass
    if not has_usable_content(result):
        stats.bump("tba")
        logger.info("TBA conference (no dates yet): %s", result.get("title"))
    if conf_id and has_deadline_within_days(result, NOTIFY_WINDOW_DAYS):
        if notify(result):
            db.mark_notified_with_retry(conf_id)
            stats.bump("notifications_sent")
    else:
        logger.info("No deadline within %d days — saved but not announced: %s", NOTIFY_WINDOW_DAYS, result.get("title"))
    return Outcome.SAVED
