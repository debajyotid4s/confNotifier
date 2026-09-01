"""scraper/db/seen_links/read.py — read path."""

from scraper.db.connection import _safe, db_cursor
from scraper.db.seen_links.constants import TERMINAL_STATUSES


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
