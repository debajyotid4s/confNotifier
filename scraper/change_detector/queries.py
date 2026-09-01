import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from scraper import db

from .constants import CLASSIFY_INTERVAL_HOURS
from .state import _as_utc

logger = logging.getLogger(__name__)


def _classification_due(domains: list[str]) -> set[str]:
    """Subset of `domains` whose last triage is older than the interval."""
    if not domains:
        return set()
    try:
        with db.db_cursor() as cur:
            cur.execute(
                "SELECT domain, last_classified_at FROM domain_stats WHERE domain = ANY(%s)",
                (domains,),
            )
            rows = cur.fetchall()
    except Exception as e:
        logger.error("change_detector: _classification_due error: %s", e)
        return set()
    seen = {}
    now = datetime.now(timezone.utc)
    for domain, last_at in rows:
        if not last_at:
            seen[domain] = True
            continue
        hours = (now - _as_utc(last_at)).total_seconds() / 3600
        seen[domain] = hours >= CLASSIFY_INTERVAL_HOURS
    return {d for d in domains if seen.get(d, True)}


def _prev_links(domain: str, limit: int = 10) -> list[str]:
    """Conference links this domain produced before, filtered in SQL.

    The previous implementation selected every homepage URL in the table and
    filtered in Python, once per flagged domain.
    """
    try:
        with db.db_cursor() as cur:
            cur.execute(
                "SELECT url FROM seen_links WHERE source = 'homepage' "
                "AND (url LIKE %s OR url LIKE %s) ORDER BY first_seen DESC LIMIT %s",
                (f"%//{domain}/%", f"%.{domain}/%", limit),
            )
            rows = [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error("change_detector: _prev_links error for %s: %s", domain, e)
        return []
    confirmed = []
    for url in rows:
        host = (urlparse(url).hostname or "").lower()
        if host == domain or host.endswith("." + domain):
            confirmed.append(url)
    return confirmed
