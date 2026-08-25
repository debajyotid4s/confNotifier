"""BD Conference Bot — pipeline orchestrator.

    Phase 1  discover  — university homepages + curated special sources
    Phase 2  requeue   — pending and back-off-eligible URLs from earlier runs
    Phase 3  extract   — dedup pre-checks, then LLM extraction and validation
    Phase 4  notify    — Telegram push for deadlines inside the notify window
    Phase 5  verify    — interval-guarded deadline re-check (see verifier.py)

Every database operation opens and closes its own connection: the run spends
minutes inside Playwright and Gemini, and Neon closes idle connections.

Run as: pip install -e . && python scraper/main.py
"""

import logging
import os
import sys
import threading
from datetime import datetime
from enum import Enum, auto

import requests

from scraper import db
from scraper.browser import PlaywrightManager
from scraper.dedup import ConferenceIndex
from scraper.extractor import daily_quota_exhausted, extract, total_requests_today
from scraper.notifier import notify, notify_pending
from scraper.patterns import classify_link
from scraper.schema import SUBMISSION_TYPES, coerce_date
from scraper.sources import homepage_links, special
from scraper.validation import has_usable_content, validate_extraction
from scraper.verifier import verify_deadlines

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.75
NOTIFY_WINDOW_DAYS = 30

#: Status writes are buffered and flushed in batches. Pre-check rejections can
#: number in the hundreds per run, and each one used to cost its own connection.
STATUS_FLUSH_EVERY = 50

REQUIRED_ENV_VARS = ["DATABASE_URL", "GOOGLE_AI_KEY", "TELEGRAM_BOT_TOKEN"]
CHANNEL_ENV_VARS = ["TELEGRAM_CHANNEL_ID", "TELEGRAM_CHANNEL_LINK"]


class Outcome(Enum):
    """What happened to one candidate URL.

    Terminal outcomes are never revisited; FAILED_* outcomes are retried on a
    later run with widening backoff.
    """

    ALREADY_DECIDED = auto()      # already terminal in seen_links
    DUPLICATE_URL = auto()        # this URL is already a saved conference
    DUPLICATE_EDITION = auto()    # same edition, different URL — merged
    STALE_URL = auto()            # hostname/path advertises a past edition
    NOT_CONFERENCE = auto()       # model says no
    LOW_CONFIDENCE = auto()       # below MIN_CONFIDENCE
    PAST_CONFERENCE = auto()      # already happened
    INVALID_PERMANENT = auto()    # page contradicts itself — do not retry
    SAVED = auto()                # new conference stored
    UPDATED = auto()              # existing conference refreshed
    FAILED_EXTRACTION = auto()    # fetch/LLM failure — retry
    FAILED_SAVE = auto()          # DB write failure — retry
    FAILED_VALIDATION = auto()    # swap suspected — retry

#: seen_links status to persist for each terminal outcome.
_TERMINAL_STATUS = {
    Outcome.DUPLICATE_URL: "extracted",
    Outcome.DUPLICATE_EDITION: "extracted",
    Outcome.STALE_URL: "not_conference",
    Outcome.NOT_CONFERENCE: "not_conference",
    Outcome.LOW_CONFIDENCE: "low_confidence",
    Outcome.PAST_CONFERENCE: "not_conference",
    Outcome.INVALID_PERMANENT: "low_confidence",
    Outcome.SAVED: "extracted",
    Outcome.UPDATED: "extracted",
    Outcome.FAILED_EXTRACTION: "failed_transient",
    Outcome.FAILED_SAVE: None,          # leave pending: the page was fine
    Outcome.FAILED_VALIDATION: "failed_transient",
    Outcome.ALREADY_DECIDED: None,
}

_SKIPPED = frozenset({
    Outcome.ALREADY_DECIDED, Outcome.DUPLICATE_URL, Outcome.DUPLICATE_EDITION,
    Outcome.STALE_URL, Outcome.NOT_CONFERENCE, Outcome.LOW_CONFIDENCE,
    Outcome.PAST_CONFERENCE, Outcome.INVALID_PERMANENT, Outcome.UPDATED,
})


class RunStats:
    """Counters for one pipeline run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.found = 0
        self.new = 0
        self.skipped = 0
        self.failed = 0
        self.quota_exhausted = False
        self.discovered = 0
        self.inserted = 0
        self.updated = 0
        self.merged = 0
        self.tba = 0
        self.notifications_sent = 0

    def tally(self, outcome: Outcome) -> None:
        with self._lock:
            if outcome is Outcome.SAVED:
                self.new += 1
            elif outcome in _SKIPPED:
                self.skipped += 1
            else:
                self.failed += 1

    def bump(self, field: str, by: int = 1) -> None:
        with self._lock:
            setattr(self, field, getattr(self, field) + by)

    def log_summary(self) -> None:
        logger.info(
            "=== Run complete: %d found, %d new, %d skipped, %d failed | LLM requests today: %d ===",
            self.found, self.new, self.skipped, self.failed, total_requests_today(),
        )
        logger.info(
            "=== Detail: discovered=%d inserted=%d updated=%d merged=%d tba=%d notified=%d ===",
            self.discovered, self.inserted, self.updated, self.merged,
            self.tba, self.notifications_sent,
        )


class StatusWriter:
    """Buffers seen_links status updates and flushes them in batches."""

    def __init__(self, flush_every: int = STATUS_FLUSH_EVERY) -> None:
        self._pending: list[tuple[str, str]] = []
        self._flush_every = flush_every

    def set(self, url: str, status: str | None) -> None:
        if not status:
            return
        self._pending.append((url, status))
        if len(self._pending) >= self._flush_every:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        db.mark_url_statuses(self._pending)
        logger.debug("StatusWriter: flushed %d status update(s)", len(self._pending))
        self._pending.clear()


# ── Startup checks ────────────────────────────────────────────────────────────

def _check_environment() -> None:
    """Fail fast on missing configuration. Only names and lengths are logged."""
    missing = [
        var for var in REQUIRED_ENV_VARS
        if not (os.environ.get(var) or "").strip()
    ]
    for var in REQUIRED_ENV_VARS:
        value = os.environ.get(var)
        if value and value.strip():
            logger.info("%s: OK (%d chars)", var, len(value))

    if missing:
        print(f"ERROR: Missing or empty environment variable(s): {', '.join(missing)}")
        print("  Set it in GitHub repo -> Settings -> Secrets -> Actions")
        sys.exit(1)

    if not any((os.environ.get(var) or "").strip() for var in CHANNEL_ENV_VARS):
        print(f"ERROR: Missing environment variable: {' or '.join(CHANNEL_ENV_VARS)}")
        sys.exit(1)


def _verify_dependencies() -> None:
    """Confirm the database and Telegram channel are reachable before starting."""
    try:
        db.get_connection().close()
        logger.info("Connected to PostgreSQL")
    except Exception as e:
        logger.critical("Cannot connect to PostgreSQL: %s", e)
        sys.exit(1)

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    channel = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": channel}, timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Telegram channel access verified")
        else:
            logger.warning("Telegram channel check failed (%d)", resp.status_code)
    except Exception as e:
        logger.warning("Telegram channel check error: %s", e)


# ── Phase 1-2: discovery and requeue ──────────────────────────────────────────

def _discover_candidates(playwright, stats: RunStats) -> list[str]:
    """Collect candidate URLs from every discovery source."""
    candidates: list[str] = []

    for name, run_source in (
        ("homepage_links", lambda: homepage_links.run(playwright=playwright)),
        ("special", special.run),
    ):
        try:
            found = run_source()
            candidates += found
            logger.info("%s returned %d candidate(s)", name, len(found))
        except Exception as e:
            logger.error("%s failed: %s", name, e)

    unique = sorted(set(candidates))
    stats.bump("discovered", len(unique))
    return unique


def _requeue_previous_runs(candidates: list[str]) -> tuple[list[str], set[str]]:
    """Merge pending and back-off-eligible URLs from earlier runs."""
    pending = db.load_pending_urls()
    if pending:
        logger.info("Re-queued %d pending URL(s) from previous runs", len(pending))

    retryable = {url for url, _ in db.load_retryable_urls()}
    if retryable:
        logger.info("Re-queued %d retryable URL(s) from previous runs", len(retryable))

    return sorted(set(candidates) | set(pending) | retryable), retryable


# ── Phase 3: extraction ───────────────────────────────────────────────────────

def _parse_root_year_tag(url: str) -> tuple[str, int | None]:
    """Split a `root_year:{year}:{url}` candidate emitted by special sources.

    These were already checked against the conferences table by the source, so
    they skip the dedup pre-checks.
    """
    if url.startswith("root_year:"):
        _, year, real_url = url.split(":", 2)
        return real_url, int(year)
    return url, None


def _extracted_deadlines(result: dict) -> list:
    """Parsed deadline dates present in an extraction."""
    return [
        d for d in (coerce_date(result.get(f"{t}_deadline")) for t in SUBMISSION_TYPES)
        if d is not None
    ]


def _has_deadline_within_days(result: dict, days: int) -> bool:
    """True when a deadline falls between today and `days` from now."""
    today = datetime.now().date()
    return any(0 <= (d - today).days <= days for d in _extracted_deadlines(result))


def _is_conference_in_past(result: dict) -> bool:
    """True when the conference start date has already passed."""
    start = coerce_date(result.get("date_start"))
    return start is not None and start < datetime.now().date()


def _precheck(url: str, index: ConferenceIndex, terminal: set[str]) -> Outcome | None:
    """Reject a candidate before spending an LLM call. None means "go ahead"."""
    if url in terminal:
        logger.debug("Already decided, skipping: %s", url)
        return Outcome.ALREADY_DECIDED

    if index.find_by_url(url) is not None:
        logger.info("Duplicate (URL already saved), skipping: %s", url)
        return Outcome.DUPLICATE_URL

    accepted, reason = classify_link(url)
    if not accepted and reason in ("stale_year", "stale_wording"):
        # Only the year/archival rejections are applied here: a URL may have
        # reached us from a curated source that legitimately does not match the
        # homepage link patterns.
        logger.info("Stale edition (%s), skipping: %s", reason, url)
        return Outcome.STALE_URL
    return None


def _process_candidate(url: str, playwright, index: ConferenceIndex,
                       terminal: set[str], retryable: set[str],
                       stats: RunStats) -> tuple[str, Outcome]:
    """Extract, validate and persist one candidate. Returns (url, outcome)."""
    if url in retryable:
        db.increment_retry(url)

    url, root_year = _parse_root_year_tag(url)

    if root_year is None:
        rejected = _precheck(url, index, terminal)
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
        return url, Outcome.FAILED_EXTRACTION

    if not result.get("is_conference", False):
        logger.info("Not a conference: %s", url)
        return url, Outcome.NOT_CONFERENCE

    confidence = result.get("confidence") or 0
    if confidence < MIN_CONFIDENCE:
        logger.warning("Low confidence %.2f for %s", confidence, url)
        return url, Outcome.LOW_CONFIDENCE

    if _is_conference_in_past(result):
        logger.info("Conference already past: %s", url)
        return url, Outcome.PAST_CONFERENCE

    # Identity dedup. The URL we crawled and the website the model reports are
    # often different, so both are checked:
    #   - the reported website already saved  -> plain duplicate, nothing to do
    #   - same title+edition under another URL -> merge into the existing row
    existing_id = None
    if root_year is None:
        reported = result.get("website") or url
        deadlines = _extracted_deadlines(result)
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


def _save_and_notify(url: str, result: dict, index: ConferenceIndex,
                     existing_id: int | None, stats: RunStats) -> Outcome:
    """Persist a validated extraction and announce it when a deadline is near."""
    result["raw_source"] = url
    success, was_inserted, conf_id = db.save_conference(result, existing_id=existing_id)
    if not success:
        logger.error("Conference save failed for %s — will retry next run", url)
        return Outcome.FAILED_SAVE

    # Keep the in-memory index current so later candidates in this same run
    # dedup against what we just wrote.
    if conf_id:
        index.add(conf_id, result.get("website") or url, result.get("title"),
                  result.get("date_start"), _extracted_deadlines(result))

    if existing_id is not None:
        logger.info("Merged duplicate edition into conference %s: %s",
                    existing_id, result.get("title"))
        stats.bump("merged")
        return Outcome.DUPLICATE_EDITION

    if not was_inserted:
        logger.info("Conference already in DB (deadlines refreshed): %s", result.get("title"))
        stats.bump("updated")
        return Outcome.UPDATED

    logger.info("New conference saved: %s", result.get("title"))
    stats.bump("inserted")

    if not has_usable_content(result):
        stats.bump("tba")
        logger.info("TBA conference (no dates yet): %s", result.get("title"))

    if conf_id and _has_deadline_within_days(result, NOTIFY_WINDOW_DAYS):
        if notify(result):
            db.mark_notified_with_retry(conf_id)
            stats.bump("notifications_sent")
    else:
        logger.info("No deadline within %d days — saved but not announced: %s",
                    NOTIFY_WINDOW_DAYS, result.get("title"))

    return Outcome.SAVED


def _run_extraction_loop(candidates: list[str], retryable: set[str],
                         index: ConferenceIndex, terminal: set[str],
                         playwright, stats: RunStats) -> None:
    """Process candidates in order until the daily LLM budget runs out."""
    statuses = StatusWriter()
    try:
        for idx, candidate in enumerate(candidates):
            if stats.quota_exhausted:
                logger.warning("Daily quota exhausted — %d URL(s) remain pending for next run",
                               len(candidates) - idx)
                break
            url, outcome = _process_candidate(
                candidate, playwright, index, terminal, retryable, stats
            )
            statuses.set(url, _TERMINAL_STATUS.get(outcome))
            stats.tally(outcome)
    finally:
        statuses.flush()


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run():
    """Discover, extract, deduplicate, notify, verify."""
    _check_environment()
    _verify_dependencies()

    logger.info("=== BD Conference Bot Run Started ===")

    try:
        with PlaywrightManager() as playwright:
            stats = RunStats()

            candidates = _discover_candidates(playwright, stats)
            candidates, retryable = _requeue_previous_runs(candidates)

            index = db.load_conference_index()
            terminal = db.load_terminal_urls()
            logger.info("Dedup index: %d conference(s); %d URL(s) already decided",
                        len(index), len(terminal))

            stats.found = len(candidates)
            logger.info("Phase 3: processing %d unique candidate(s)", len(candidates))
            _run_extraction_loop(candidates, retryable, index, terminal, playwright, stats)
            stats.log_summary()

            # Flush any conference saved but not yet announced, including
            # backlog from runs where notification failed.
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


if __name__ == "__main__":
    run()
