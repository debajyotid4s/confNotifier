"""scraper/db/seen_links — package facade."""

from scraper.db.seen_links.constants import (  # noqa: F401
    MAX_RETRIES,
    RETRY_BACKOFF_HOURS,
    TERMINAL_STATUSES,
    _terminal_sql,
)
from scraper.db.seen_links.read import (  # noqa: F401
    is_url_processed,
    load_pending_urls,
    load_seen_urls,
    load_terminal_urls,
)
from scraper.db.seen_links.retry import increment_retry, load_retryable_urls  # noqa: F401
from scraper.db.seen_links.write import (  # noqa: F401
    mark_url_status,
    mark_url_statuses,
    save_seen_link,
    save_seen_links_bulk,
)

__all__ = [
    "TERMINAL_STATUSES", "MAX_RETRIES", "RETRY_BACKOFF_HOURS", "_terminal_sql",
    "save_seen_link", "save_seen_links_bulk", "mark_url_status", "mark_url_statuses",
    "load_seen_urls", "load_terminal_urls", "is_url_processed", "load_pending_urls",
    "load_retryable_urls", "increment_retry",
]
