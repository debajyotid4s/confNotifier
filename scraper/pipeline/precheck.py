"""scraper/pipeline/precheck.py — helpers for candidate filtering."""

import logging
from datetime import datetime

from scraper.dedup import ConferenceIndex
from scraper.patterns import classify_link
from scraper.pipeline.outcomes import Outcome
from scraper.schema import SUBMISSION_TYPES, coerce_date

logger = logging.getLogger(__name__)


def parse_root_year_tag(url: str) -> tuple[str, int | None]:
    """Split a `root_year:{year}:{url}` candidate emitted by special sources."""
    if url.startswith("root_year:"):
        _, year, real_url = url.split(":", 2)
        return real_url, int(year)
    return url, None


def extracted_deadlines(result: dict) -> list:
    """Parsed deadline dates present in an extraction."""
    return [d for d in (coerce_date(result.get(f"{t}_deadline")) for t in SUBMISSION_TYPES) if d is not None]


def has_deadline_within_days(result: dict, days: int) -> bool:
    """True when a deadline falls between today and `days` from now."""
    today = datetime.now().date()
    return any(0 <= (d - today).days <= days for d in extracted_deadlines(result))


def is_conference_in_past(result: dict) -> bool:
    """True when the conference start date has already passed."""
    start = coerce_date(result.get("date_start"))
    return start is not None and start < datetime.now().date()


def precheck(url: str, index: ConferenceIndex, terminal: set[str]) -> Outcome | None:
    """Reject a candidate before spending an LLM call. None means 'go ahead'."""
    if url in terminal:
        logger.debug("Already decided, skipping: %s", url)
        return Outcome.ALREADY_DECIDED
    if index.find_by_url(url) is not None:
        logger.info("Duplicate (URL already saved), skipping: %s", url)
        return Outcome.DUPLICATE_URL
    accepted, reason = classify_link(url)
    if not accepted and reason in ("stale_year", "stale_wording"):
        logger.info("Stale edition (%s), skipping: %s", reason, url)
        return Outcome.STALE_URL
    return None
