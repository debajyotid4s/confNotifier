"""scraper/pipeline/runner/runner.py — top-level run."""

import logging

from scraper import db
from scraper.browser import PlaywrightManager
from scraper.notifier import notify, notify_pending
from scraper.pipeline.checks import check_environment, verify_dependencies
from scraper.pipeline.discovery import discover_candidates, requeue_previous_runs
from scraper.pipeline.runner.loop import _run_extraction_loop
from scraper.pipeline.stats import RunStats
from scraper.verifier import verify_deadlines

logger = logging.getLogger(__name__)


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
