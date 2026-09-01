"""scraper/db/seen_links/write.py — write path."""

from psycopg2.extras import execute_values

from scraper.db.connection import _safe, db_cursor
from scraper.db.seen_links.constants import TERMINAL_STATUSES, _terminal_sql


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
