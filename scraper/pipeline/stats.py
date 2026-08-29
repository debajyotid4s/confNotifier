"""scraper/pipeline/stats.py — RunStats counters."""

import threading

from scraper.extractor import total_requests_today

from scraper.pipeline.outcomes import Outcome, _SKIPPED
import logging

logger = logging.getLogger(__name__)


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
