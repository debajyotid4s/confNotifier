"""scraper/pipeline/discovery.py — Phase 1-2: discovery and requeue."""

import logging

from scraper import db
from scraper.sources import homepage_links, special

logger = logging.getLogger(__name__)


def discover_candidates(playwright, stats) -> list[str]:
    """Collect candidate URLs from every discovery source."""
    candidates: list[str] = []

    def _on_rejected(url, anchor_text):
        try:
            from data_collection.collector import record_unconfirmed
            record_unconfirmed(url, reason="regex_rejected", anchor_text=anchor_text)
        except Exception:
            pass

    for name, run_source in (
        ("homepage_links", lambda: homepage_links.run(playwright=playwright, on_rejected=_on_rejected)),
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


def requeue_previous_runs(candidates: list[str]) -> tuple[list[str], set[str]]:
    """Merge pending and back-off-eligible URLs from earlier runs."""
    pending = db.load_pending_urls()
    if pending:
        logger.info("Re-queued %d pending URL(s) from previous runs", len(pending))

    retryable = {url for url, _ in db.load_retryable_urls()}
    if retryable:
        logger.info("Re-queued %d retryable URL(s) from previous runs", len(retryable))

    return sorted(set(candidates) | set(pending) | retryable), retryable
