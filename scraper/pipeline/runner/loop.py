"""scraper/pipeline/runner/loop.py — extraction loop."""

import logging

from scraper.dedup import ConferenceIndex
from scraper.pipeline.outcomes import _TERMINAL_STATUS
from scraper.pipeline.runner.candidate import _process_candidate
from scraper.pipeline.stats import RunStats
from scraper.pipeline.status_writer import StatusWriter

logger = logging.getLogger(__name__)


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
