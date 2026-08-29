"""scraper/pipeline/runner.py — Phase 3-5: extraction, save, notify, verify."""

import logging

from scraper import db
from scraper.browser import PlaywrightManager
from scraper.dedup import ConferenceIndex
from scraper.extractor import daily_quota_exhausted, extract
from scraper.notifier import notify, notify_pending
from scraper.pipeline.checks import check_environment, verify_dependencies
from scraper.pipeline.discovery import discover_candidates, requeue_previous_runs
from scraper.pipeline.outcomes import NOTIFY_WINDOW_DAYS, MIN_CONFIDENCE, Outcome, _TERMINAL_STATUS
from scraper.pipeline.precheck import extracted_deadlines, has_deadline_within_days, is_conference_in_past, parse_root_year_tag, precheck
from scraper.pipeline.stats import RunStats
from scraper.pipeline.status_writer import StatusWriter
from scraper.validation import has_usable_content, validate_extraction
from scraper.verifier import verify_deadlines

logger = logging.getLogger(__name__)


def _process_candidate(url: str, playwright, index: ConferenceIndex, terminal: set[str], retryable: set[str], stats: RunStats) -> tuple[str, Outcome]:
    """Extract, validate and persist one candidate. Returns (url, outcome)."""
    if url in retryable:
        db.increment_retry(url)

    url, root_year = parse_root_year_tag(url)

    if root_year is None:
        rejected = precheck(url, index, terminal)
        if rejected is not None:
            return url, rejected

    logger.info("Extracting data from: %s", url)
    try:
        result = extract(url, playwright)
    except RuntimeError as e:
        if "Daily quota exhausted" in str(e):
            stats.quota_exhausted = True
            logger.warning("Daily quota exhausted, stopping extraction")
            return url, Outcome.FAILED_EXTRACTION
        logger.error("Unexpected error for %s: %s", url, e)
        return url, Outcome.FAILED_EXTRACTION
    except Exception as e:
        logger.error("Unexpected error for %s: %s", url, e)
        return url, Outcome.FAILED_EXTRACTION

    if result is None:
        if daily_quota_exhausted():
            stats.quota_exhausted = True
        logger.warning("Extraction failed for: %s", url)
        try:
            from data_collection.collector import record_unconfirmed
            record_unconfirmed(url, reason="fetch_failed")
        except Exception:
            pass
        return url, Outcome.FAILED_EXTRACTION

    if not result.get("is_conference", False):
        logger.info("Not a conference: %s", url)
        try:
            from data_collection.collector import record_unconfirmed
            record_unconfirmed(url, reason="not_conference", page_title=result.get("title"))
        except Exception:
            pass
        return url, Outcome.NOT_CONFERENCE

    confidence = result.get("confidence") or 0
    if confidence < MIN_CONFIDENCE:
        logger.warning("Low confidence %.2f for %s", confidence, url)
        try:
            from data_collection.collector import record_unconfirmed
            record_unconfirmed(url, reason="low_confidence", page_title=result.get("title"))
        except Exception:
            pass
        return url, Outcome.LOW_CONFIDENCE

    if is_conference_in_past(result):
        logger.info("Conference already past: %s", url)
        return url, Outcome.PAST_CONFERENCE

    existing_id = None
    if root_year is None:
        reported = result.get("website") or url
        deadlines = extracted_deadlines(result)
        if index.find_by_url(reported) is not None:
            logger.info("Duplicate conference (website already saved): %s", url)
            return url, Outcome.DUPLICATE_URL
        existing_id = index.find_by_identity(
            title=result.get("title"),
            date_start=result.get("date_start"),
            website=reported,
            deadlines=deadlines,
        )

    stored = db.get_stored_submission_deadlines(result.get("website") or url)
    verdict = validate_extraction(result, stored_deadlines=stored)
    if not verdict:
        if verdict.permanent:
            logger.warning("%s at %s — not retrying", verdict.reason, url)
            return url, Outcome.INVALID_PERMANENT
        logger.warning("%s at %s — retry next run", verdict.reason, url)
        return url, Outcome.FAILED_VALIDATION

    return url, _save_and_notify(url, result, index, existing_id, stats)


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


def _run_extraction_loop(candidates: list[str], retryable: set[str], index: ConferenceIndex, terminal: set[str], playwright, stats: RunStats) -> None:
    """Process candidates in order until the daily LLM budget runs out."""
    statuses = StatusWriter()
    try:
        for idx, candidate in enumerate(candidates):
            if stats.quota_exhausted:
                logger.warning("Daily quota exhausted — %d URL(s) remain pending for next run", len(candidates) - idx)
                break
            url, outcome = _process_candidate(candidate, playwright, index, terminal, retryable, stats)
            statuses.set(url, _TERMINAL_STATUS.get(outcome))
            stats.tally(outcome)
    finally:
        statuses.flush()


def run():
    """Discover, extract, deduplicate, notify, verify."""
    check_environment()
    verify_dependencies()
    logger.info("=== BD Conference Bot Run Started ===")
    try:
        with PlaywrightManager() as playwright:
            stats = RunStats()
            candidates = discover_candidates(playwright, stats)
            candidates, retryable = requeue_previous_runs(candidates)
            index = db.load_conference_index()
            terminal = db.load_terminal_urls()
            logger.info("Dedup index: %d conference(s); %d URL(s) already decided", len(index), len(terminal))
            stats.found = len(candidates)
            logger.info("Phase 3: processing %d unique candidate(s)", len(candidates))
            _run_extraction_loop(candidates, retryable, index, terminal, playwright, stats)
            stats.log_summary()
            sent = notify_pending(notify)
            if sent:
                logger.info("notify_pending: sent %d notification(s)", sent)
            try:
                verify_deadlines(playwright)
            except Exception as e:
                logger.error("deadline_verification: uncaught error: %s", e)
    except Exception as e:
        logger.critical("PlaywrightManager failed to launch — skipping browser phases: %s", e)
        logger.info("=== Run complete (partial — browser unavailable) ===")
