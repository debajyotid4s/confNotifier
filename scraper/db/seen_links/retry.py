"""scraper/db/seen_links/retry.py — retry backoff."""

import logging
from datetime import datetime, timezone

from scraper.db.connection import _safe, db_cursor
from scraper.db.seen_links.constants import MAX_RETRIES, RETRY_BACKOFF_HOURS

logger = logging.getLogger(__name__)


@_safe("load_retryable_urls", default=list)
def load_retryable_urls() -> list[tuple[str, int]]:
    """failed_transient URLs whose backoff window has elapsed."""
    now = datetime.now(timezone.utc)
    retryable: list[tuple[str, int]] = []
    exhausted: list[str] = []

    with db_cursor() as cur:
        cur.execute(
            "SELECT url, COALESCE(retry_count, 0), last_attempt_at FROM seen_links "
            "WHERE status = 'failed_transient'"
        )
        rows = cur.fetchall()

    for url, retry_count, last_attempt_at in rows:
        if retry_count >= MAX_RETRIES:
            exhausted.append(url)
            continue
        if last_attempt_at is None:
            retryable.append((url, retry_count))
            continue
        hours_since = (now - last_attempt_at).total_seconds() / 3600
        if hours_since >= RETRY_BACKOFF_HOURS[retry_count]:
            retryable.append((url, retry_count))

    if exhausted:
        logger.warning("Retries exhausted for %d URL(s), demoting to failed_permanent", len(exhausted))
        from scraper.db.seen_links.write import mark_url_statuses
        mark_url_statuses([(u, "failed_permanent") for u in exhausted])
    return retryable


@_safe("increment_retry")
def increment_retry(url: str) -> None:
    """Count one more attempt against a retryable URL."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE seen_links SET retry_count = COALESCE(retry_count, 0) + 1, "
            "last_attempt_at = NOW() WHERE url = %s",
            (url,),
        )
