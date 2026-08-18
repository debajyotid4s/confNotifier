"""BD Conference Bot — pipeline orchestrator.

Discover, extract, deduplicate, notify, and verify conference deadlines:

    Phase 1-2  discovery  — homepage links + special sources (see sources/)
    Phase 3    requeue    — merge pending/retryable URLs from previous runs
    Phase 4    extract    — LLM extraction with dedup pre-checks and validation
    Phase 5    notify     — Telegram push for deadlines within 30 days
    Phase 6    verify     — interval-guarded deadline re-check (see verifier.py)

Every DB operation opens and closes its own connection — no long-lived
connection is held during source scanning or LLM extraction (Neon idle
timeout requirement).

Runs as: pip install -e . && python scraper/main.py
"""

import logging
import os
import re
import sys
import threading
from datetime import datetime
from enum import Enum, auto
from urllib.parse import urlparse

import requests

from scraper import db
from scraper.browser import PlaywrightManager
from scraper.extractor import extract, daily_quota_exhausted, total_requests_today
from scraper.notifier import notify, notify_pending
from scraper.schema import DEADLINE_TYPES
from scraper.sources import homepage_links, special
from scraper.validation import (
    _parse_date_safe,
    _check_chronological_order,
    _check_deadline_context,
)
from scraper.verifier import verify_deadlines

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.75
NOTIFY_WINDOW_DAYS = 30

REQUIRED_ENV_VARS = ["DATABASE_URL", "GOOGLE_AI_KEY", "TELEGRAM_BOT_TOKEN"]
CHANNEL_ENV_VARS = ["TELEGRAM_CHANNEL_ID", "TELEGRAM_CHANNEL_LINK"]


class CandidateOutcome(Enum):
    """Result of processing a single candidate URL.

    The outcome drives the run summary counters:
      new     — SAVED
      skipped — terminal decisions (never re-checked)
      failed  — transient problems (retried on a later run)
    """

    PROCESSED = auto()          # already in a terminal seen_links state
    DUPLICATE = auto()          # website already in conferences table
    PAST_YEAR_URL = auto()      # hostname embeds a past year
    NOT_CONFERENCE = auto()     # LLM: not a conference
    LOW_CONFIDENCE = auto()     # LLM confidence below threshold
    PAST_CONFERENCE = auto()    # conference already ended
    EXTRACTION_FAILED = auto()  # page fetch / LLM failure — retry next run
    SAVE_FAILED = auto()        # DB write failure — retry next run
    VALIDATION_FAILED = auto()  # chronology/context violated — retry next run
    SAVED = auto()              # new conference persisted
    UPDATED = auto()            # existing conference refreshed


class RunStats:
    """Aggregates counters for one pipeline run. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.found = 0
        self.new = 0
        self.skipped = 0
        self.failed = 0
        self.quota_exhausted = False

    def tally(self, outcome: CandidateOutcome) -> None:
        with self._lock:
            if outcome is CandidateOutcome.SAVED:
                self.new += 1
                return
            if outcome in {
                CandidateOutcome.PROCESSED,
                CandidateOutcome.DUPLICATE,
                CandidateOutcome.PAST_YEAR_URL,
                CandidateOutcome.NOT_CONFERENCE,
                CandidateOutcome.LOW_CONFIDENCE,
                CandidateOutcome.PAST_CONFERENCE,
                CandidateOutcome.UPDATED,
            }:
                self.skipped += 1
                return
            self.failed += 1

    def log_summary(self) -> None:
        logger.info(
            "=== Run complete: %d found, %d new, %d skipped, %d failed | "
            "LLM requests today: %d ===",
            self.found, self.new, self.skipped, self.failed,
            total_requests_today(),
        )


# ── Startup checks ──


def _check_environment() -> None:
    """Fail fast when required environment variables are missing.

    Only presence/length is logged — never any part of a secret value.
    """
    missing = []
    for var in REQUIRED_ENV_VARS:
        value = os.environ.get(var)
        if not value or not value.strip():
            missing.append(var)
        else:
            logger.info("%s: OK (%d chars)", var, len(value))

    if missing:
        print(f"ERROR: Missing or empty environment variable(s): {', '.join(missing)}")
        print("  Set it in GitHub repo -> Settings -> Secrets -> Actions")
        sys.exit(1)

    if not any(os.environ.get(var, "").strip() for var in CHANNEL_ENV_VARS):
        print(f"ERROR: Missing environment variable: {' or '.join(CHANNEL_ENV_VARS)}")
        sys.exit(1)


def _verify_dependencies() -> None:
    """Check DB connectivity and Telegram channel access."""
    try:
        conn = db.get_connection()
        conn.close()
        logger.info("Connected to PostgreSQL")
    except Exception as e:
        logger.critical("Cannot connect to PostgreSQL: %s", e)
        sys.exit(1)

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    channel = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": channel},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Telegram channel access verified")
        else:
            logger.warning("Telegram channel check failed (%d): %s", resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Telegram channel check error: %s", e)


# ── Phases 1-3: discovery and requeue ──


def _discover_candidates(playwright) -> list[str]:
    """Phase 1-2: collect candidates from homepage and special sources."""
    candidates: list[str] = []

    try:
        candidates += homepage_links.run(playwright=playwright)
        logger.info("homepage_links returned %d candidates", len(candidates))
    except Exception as e:
        logger.error("homepage_links failed: %s", e)

    try:
        candidates += special.run()
        logger.info("special returned %d candidates", len(candidates))
    except Exception as e:
        logger.error("special failed: %s", e)

    return list(set(candidates))


def _requeue_previous_runs(candidates: list[str]) -> tuple[list[str], set[str]]:
    """Phase 3: merge pending and retryable URLs from previous runs.

    Returns (candidates, retryable_url_set).
    """
    pending = db.load_pending_urls()
    if pending:
        logger.info("Re-queued %d pending URLs from previous runs", len(pending))
    candidates = list(set(candidates + pending))

    retryable = db.load_retryable_urls()
    retryable_url_set = {url for url, _ in retryable}
    if retryable_url_set:
        logger.info("Re-queued %d retryable URLs from previous runs", len(retryable_url_set))
    candidates = list(set(candidates + list(retryable_url_set)))

    return candidates, retryable_url_set


# ── Phase 4: candidate extraction ──


def _parse_root_year_tag(url: str) -> tuple[str, tuple[str, int] | None]:
    """Split 'root_year:{year}:{url}' tagged candidates from special sources."""
    if url.startswith("root_year:"):
        parts = url.split(":", 2)
        return parts[2], (parts[2], int(parts[1]))
    return url, None


def _has_past_year_in_hostname(url: str, now: datetime) -> bool:
    """True when the hostname embeds a year before the current one.

    (e.g. icap2025.sust.edu when current year is 2026)
    """
    hostname = urlparse(url).hostname or ""
    match = re.search(r"(\d{4})", hostname)
    return bool(match and int(match.group(1)) < now.year)


def _has_deadline_within_days(result: dict, days: int) -> bool:
    """True if any extracted deadline falls within the next `days` days."""
    today = datetime.now().date()
    for typ in DEADLINE_TYPES:
        deadline = result.get(f"{typ}_deadline")
        if not deadline:
            continue
        try:
            deadline_date = datetime.strptime(deadline, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if 0 <= (deadline_date - today).days <= days:
            return True
    return False


def _is_conference_in_past(result: dict) -> bool:
    """True when the conference start date has already passed."""
    date_start = result.get("date_start")
    if not date_start:
        return False
    try:
        return datetime.strptime(date_start, "%Y-%m-%d").date() < datetime.now().date()
    except (ValueError, TypeError):
        return False


def _extract_candidate(url: str, playwright, stats: RunStats) -> dict | None:
    """Run LLM extraction.

    Returns None on transient failure or quota exhaustion. Sets
    stats.quota_exhausted when the daily quota is hit. Other unexpected
    errors propagate to the caller, which marks the URL for retry.
    """
    try:
        return extract(url, playwright)
    except RuntimeError as e:
        if "Daily quota exhausted" in str(e):
            stats.quota_exhausted = True
            logger.warning("Daily quota exhausted, stopping extraction")
            return None
        raise


def _validate_result(result: dict) -> str | None:
    """Run validation layers; return a reason string when invalid, else None."""
    conf_start = _parse_date_safe(result.get("date_start"))
    new_values = {
        typ: _parse_date_safe(result.get(f"{typ}_deadline"))
        for typ in DEADLINE_TYPES
    }

    # Layer B: chronological order constraint
    if not _check_chronological_order(new_values, conf_start):
        return "Chronological order violated"

    # Layer C: context keyword validation
    mismatches = _check_deadline_context(result)
    if mismatches:
        return f"Context mismatch for fields {mismatches}"

    return None


def _save_and_notify(url: str, result: dict) -> CandidateOutcome:
    """Persist a validated extraction, then notify when a deadline is due."""
    result["raw_source"] = url
    save_success, was_inserted, conf_id = db.save_conference(result)
    if not save_success:
        # DB write failed — do NOT mark as terminal; retry next run.
        logger.error("Conference save failed for %s — will retry next run", url)
        return CandidateOutcome.SAVE_FAILED

    db.mark_url_status(url, "extracted")

    if not was_inserted:
        logger.info("Conference already in DB (updated deadlines): %s", result.get("title"))
        return CandidateOutcome.UPDATED

    logger.info("New conference saved: %s", result.get("title"))

    # Only notify if at least one deadline is within the notify window.
    if _has_deadline_within_days(result, NOTIFY_WINDOW_DAYS):
        if conf_id:
            notify(result)
            db.mark_notified_with_retry(conf_id)
    else:
        logger.info(
            "No deadline within %d days — saving but NOT notifying yet: %s",
            NOTIFY_WINDOW_DAYS, result.get("title"),
        )

    return CandidateOutcome.SAVED


def _process_candidate(
    url: str,
    playwright,
    known_websites: set,
    retryable_url_set: set,
    stats: RunStats,
) -> CandidateOutcome:
    """Extract + validate + persist one candidate URL.

    Pacing is handled by the rate limiters in extractor.py.
    Quota-loop termination is owned by the caller.
    """
    if url in retryable_url_set:
        db.increment_retry(url)

    url, root_year_info = _parse_root_year_tag(url)

    # Root_year URLs were already verified by _is_edition_in_db — skip these checks.
    if not root_year_info and db.is_url_processed(url):
        logger.debug("Already processed, skipping: %s", url)
        return CandidateOutcome.PROCESSED

    # Pre-check 1: skip if conference website already in DB (before LLM cost).
    if not root_year_info and db.normalize_website(url) in known_websites:
        logger.info("Duplicate (URL already known), skipping: %s", url)
        db.mark_url_status(url, "extracted")
        return CandidateOutcome.DUPLICATE

    # Pre-check 2: skip URLs with a past year in the hostname.
    if _has_past_year_in_hostname(url, datetime.now()):
        logger.info("Subdomain contains past year, skipping: %s", url)
        db.mark_url_status(url, "not_conference")
        return CandidateOutcome.PAST_YEAR_URL

    logger.info("Extracting data from: %s", url)
    try:
        result = _extract_candidate(url, playwright, stats)
    except Exception as e:
        logger.error("Unexpected error for %s: %s", url, e)
        db.mark_url_status(url, "failed_transient")
        return CandidateOutcome.EXTRACTION_FAILED

    if result is None:
        if daily_quota_exhausted():
            stats.quota_exhausted = True
        logger.warning("Extraction failed for: %s", url)
        db.mark_url_status(url, "failed_transient")
        return CandidateOutcome.EXTRACTION_FAILED

    if not result.get("is_conference", False):
        logger.info("Not a conference, marking done: %s", url)
        db.mark_url_status(url, "not_conference")
        return CandidateOutcome.NOT_CONFERENCE

    # Skip low-confidence extractions
    if result.get("confidence", 0) < MIN_CONFIDENCE:
        logger.warning(
            "Low confidence %.2f for %s, marking done",
            result.get("confidence"), url
        )
        db.mark_url_status(url, "low_confidence")
        return CandidateOutcome.LOW_CONFIDENCE

    # Skip conferences that have already ended
    if _is_conference_in_past(result):
        logger.info("Conference already past, marking done: %s", url)
        db.mark_url_status(url, "not_conference")
        return CandidateOutcome.PAST_CONFERENCE

    # Dedup on the extracted website (root_year sources already verified).
    if not root_year_info and db.normalize_website(result.get("website", "")) in known_websites:
        logger.info("Duplicate conference, marking done: %s", url)
        db.mark_url_status(url, "extracted")
        return CandidateOutcome.DUPLICATE

    reason = _validate_result(result)
    if reason:
        logger.warning("%s at %s, retry next run", reason, url)
        db.mark_url_status(url, "failed_transient")
        return CandidateOutcome.VALIDATION_FAILED

    return _save_and_notify(url, result)


def _run_extraction_loop(
    candidates: list[str],
    retryable_url_set: set,
    known_websites: set,
    playwright,
    stats: RunStats,
) -> None:
    """Phase 4: extract candidates sequentially, respecting the daily LLM quota."""
    for idx, url in enumerate(candidates):
        if stats.quota_exhausted:
            # Quota exhausted — remaining URLs stay pending, auto-retried next run.
            logger.warning(
                "Daily quota exhausted — %d URLs remain pending for next run",
                len(candidates) - idx,
            )
            break

        outcome = _process_candidate(url, playwright, known_websites, retryable_url_set, stats)
        stats.tally(outcome)


# ── Main orchestrator ──


def run():
    """Main orchestrator: discover, extract, deduplicate, notify, verify."""
    _check_environment()
    _verify_dependencies()

    logger.info("=== BD Conference Bot Run Started ===")

    try:
        with PlaywrightManager() as playwright:

            # Phases 1-3: discovery + requeue from previous runs
            candidates = _discover_candidates(playwright)
            candidates, retryable_url_set = _requeue_previous_runs(candidates)

            known_websites = db.load_known_websites()
            logger.info(
                "Loaded %d known conference websites for dedup", len(known_websites)
            )
            logger.info("Phase 4: Processing %d unique candidates", len(candidates))

            stats = RunStats()
            stats.found = len(candidates)
            _run_extraction_loop(candidates, retryable_url_set, known_websites, playwright, stats)
            stats.log_summary()

            # Phase 5: notify any conferences saved but not yet notified
            # (includes backlog from previous runs and current run)
            pending_sent = notify_pending(notify)
            if pending_sent > 0:
                logger.info("notify_pending: sent %d notification(s)", pending_sent)

            # Phase 6: interval-guarded deadline re-verification
            try:
                verify_deadlines(playwright)
            except Exception as e:
                logger.error("deadline_verification: uncaught error: %s", e)

    except Exception as e:
        logger.critical("PlaywrightManager failed to launch — skipping browser-dependent phases: %s", e)
        logger.info("=== Run complete (partial — browser unavailable, nothing processed) ===")


if __name__ == "__main__":
    run()
