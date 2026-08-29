"""scraper.db — package facade.

This package was split from the former 698-line scraper/db.py into
focused modules (<200 lines each). Every public name is re-exported here so
`from scraper import db` and `from scraper.db import save_conference` keep
working without a single caller change.
"""

from scraper.db.connection import (  # noqa: F401
    CONNECT_ATTEMPTS,
    CONNECT_RETRY_SECONDS,
    _safe,
    db_cursor,
    get_connection,
    normalize_website,
)
from scraper.db.conferences import (  # noqa: F401
    _BASE_COLUMNS,
    get_stored_submission_deadlines,
    load_conference_index,
    save_conference,
)
from scraper.db.seen_links import (  # noqa: F401
    MAX_RETRIES,
    RETRY_BACKOFF_HOURS,
    TERMINAL_STATUSES,
    increment_retry,
    is_url_processed,
    load_pending_urls,
    load_retryable_urls,
    load_seen_urls,
    load_terminal_urls,
    mark_url_status,
    mark_url_statuses,
    save_seen_link,
    save_seen_links_bulk,
)
from scraper.db.strategies import (  # noqa: F401
    load_domain_strategies,
    load_special_path_cache,
    save_domain_strategies_bulk,
    save_domain_strategy,
    save_special_path_cache,
)
from scraper.db.telegram import (  # noqa: F401
    ensure_telegram_messages_table,
    get_last_telegram_message,
    get_task_last_run,
    mark_notified,
    mark_notified_with_retry,
    mark_past_conferences_notified,
    mark_verification_done,
    save_telegram_message,
)

__all__ = [
    "CONNECT_ATTEMPTS", "CONNECT_RETRY_SECONDS",
    "get_connection", "db_cursor", "_safe", "normalize_website",
    "TERMINAL_STATUSES", "MAX_RETRIES", "RETRY_BACKOFF_HOURS",
    "save_seen_link", "save_seen_links_bulk", "mark_url_status", "mark_url_statuses",
    "load_seen_urls", "load_terminal_urls", "is_url_processed",
    "load_pending_urls", "load_retryable_urls", "increment_retry",
    "load_domain_strategies", "save_domain_strategy", "save_domain_strategies_bulk",
    "load_special_path_cache", "save_special_path_cache",
    "save_conference", "load_conference_index", "get_stored_submission_deadlines",
    "mark_notified", "mark_notified_with_retry", "mark_past_conferences_notified",
    "mark_verification_done", "get_task_last_run",
    "ensure_telegram_messages_table", "save_telegram_message", "get_last_telegram_message",
]
