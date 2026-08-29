"""scraper/db/seen_links.py — seen_links state machine."""

import logging
from datetime import datetime, timezone

from psycopg2.extras import execute_values

from scraper.db.connection import _safe, db_cursor

logger = logging.getLogger(__name__)

#: A URL in one of these states has been decided and is never re-examined.
TERMINAL_STATUSES = ("not_conference", "low_confidence", "extracted", "failed_permanent")

MAX_RETRIES = 3
RETRY_BACKOFF_HOURS = [6, 24, 72]


def _terminal_sql() -> str:
    """TERMINAL_STATUSES as a literal SQL tuple."""
    return "(" + ", ".join(f"'{s}'" for s in TERMINAL_STATUSES) + ")"


@_safe("save_seen_link")
def save_seen_link(url, source="unknown", status="pending") -> None:
    """Record one discovered URL without demoting a terminal status."""
    save_seen_links_bulk([(url, source, status)])


@_safe("save_seen_links_bulk", default=0)
def save_seen_links_bulk(rows) -> int:
    """Record many discovered URLs in a single round-trip."""
    values = [(u, s, st) for u, s, st in rows if u]
    if not values:
        return 0
    with db_cursor(commit=True) as cur:
        execute_values(
            cur,
            "INSERT INTO seen_links (url, source, status) VALUES %s "
            "ON CONFLICT (url) DO UPDATE SET "
            "source = EXCLUDED.source, status = EXCLUDED.status, last_seen = NOW() "
            f"WHERE seen_links.status NOT IN {_terminal_sql()}",
            values,
            template="(%s, %s, %s)",
            page_size=200,
        )
    return len(values)


@_safe("mark_url_status")
def mark_url_status(url: str, status: str) -> None:
    """Move a URL to `status`, inserting it when it was never seen."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO seen_links (url, source, status) VALUES (%s, 'phase4', %s) "
            "ON CONFLICT (url) DO UPDATE SET status = %s, last_seen = NOW() "
            "WHERE seen_links.status NOT IN %s",
            (url, status, status, TERMINAL_STATUSES),
        )


@_safe("mark_url_statuses", default=0)
def mark_url_statuses(pairs) -> int:
    """Move many URLs to their statuses in one round-trip."""
    values = [(u, s) for u, s in pairs if u]
    if not values:
        return 0
    with db_cursor(commit=True) as cur:
        execute_values(
            cur,
            "INSERT INTO seen_links (url, source, status) VALUES %s "
            "ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, last_seen = NOW() "
            f"WHERE seen_links.status NOT IN {_terminal_sql()}",
            [(u, "phase4", s) for u, s in values],
            template="(%s, %s, %s)",
        )
    return len(values)


@_safe("load_seen_urls", default=set)
def load_seen_urls(source: str | None = None) -> set[str]:
    """All URLs already in seen_links, optionally limited to one source."""
    with db_cursor() as cur:
        if source:
            cur.execute("SELECT url FROM seen_links WHERE source = %s", (source,))
        else:
            cur.execute("SELECT url FROM seen_links")
        return {row[0] for row in cur.fetchall()}


@_safe("load_terminal_urls", default=set)
def load_terminal_urls() -> set[str]:
    """URLs already decided — used to skip candidates without a per-URL query."""
    with db_cursor() as cur:
        cur.execute("SELECT url FROM seen_links WHERE status IN %s", (TERMINAL_STATUSES,))
        return {row[0] for row in cur.fetchall()}


@_safe("is_url_processed", default=False)
def is_url_processed(url: str) -> bool:
    """True when this URL already reached a terminal status."""
    with db_cursor() as cur:
        cur.execute("SELECT status FROM seen_links WHERE url = %s", (url,))
        row = cur.fetchone()
    return row is not None and row[0] in TERMINAL_STATUSES


@_safe("load_pending_urls", default=list)
def load_pending_urls() -> list[str]:
    """URLs discovered earlier that still need extraction."""
    with db_cursor() as cur:
        cur.execute("SELECT url FROM seen_links WHERE status = 'pending'")
        return [row[0] for row in cur.fetchall()]


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
