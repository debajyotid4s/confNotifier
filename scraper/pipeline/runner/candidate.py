"""scraper/pipeline/runner/candidate.py — one candidate."""

import logging

from scraper import db
from scraper.dedup import ConferenceIndex
from scraper.extractor import daily_quota_exhausted, extract
from scraper.pipeline.outcomes import MIN_CONFIDENCE, Outcome
from scraper.pipeline.precheck import extracted_deadlines, is_conference_in_past, parse_root_year_tag, precheck
from scraper.pipeline.runner.persist import _save_and_notify
from scraper.pipeline.stats import RunStats
from scraper.validation import validate_extraction

logger = logging.getLogger(__name__)

def _track_unconfirmed(url, reason, title=None):
    try:
        from data_collection.collector import record_unconfirmed as rc
        rc(url, reason=reason, **({"page_title": title} if title else {}))
    except Exception:
        pass

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
        _track_unconfirmed(url, "fetch_failed")
        return url, Outcome.FAILED_EXTRACTION
    if not result.get("is_conference", False):
        logger.info("Not a conference: %s", url)
        _track_unconfirmed(url, "not_conference", result.get("title"))
        return url, Outcome.NOT_CONFERENCE
    confidence = result.get("confidence") or 0
    if confidence < MIN_CONFIDENCE:
        logger.warning("Low confidence %.2f for %s", confidence, url)
        _track_unconfirmed(url, "low_confidence", result.get("title"))
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
        existing_id = index.find_by_identity(title=result.get("title"), date_start=result.get("date_start"), website=reported, deadlines=deadlines)
    stored = db.get_stored_submission_deadlines(result.get("website") or url)
    verdict = validate_extraction(result, stored_deadlines=stored)
    if not verdict:
        if verdict.permanent:
            logger.warning("%s at %s — not retrying", verdict.reason, url)
            return url, Outcome.INVALID_PERMANENT
        logger.warning("%s at %s — retry next run", verdict.reason, url)
        return url, Outcome.FAILED_VALIDATION
    return url, _save_and_notify(url, result, index, existing_id, stats)
