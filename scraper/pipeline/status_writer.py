"""scraper/pipeline/status_writer.py — batched seen_links status writer."""

import logging

from scraper import db
from scraper.pipeline.outcomes import STATUS_FLUSH_EVERY

logger = logging.getLogger(__name__)


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
