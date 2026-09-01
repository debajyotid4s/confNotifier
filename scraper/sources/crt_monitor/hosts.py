import logging
from urllib.parse import urlparse

from scraper import db

logger = logging.getLogger(__name__)


def _load_seen_hostnames() -> set[str]:
    """Hostnames already recorded in seen_links, in any status.

    CT logs re-report the same name on every certificate renewal, so dedup is on
    hostname rather than URL. Both the bare and `www.` forms are stored so either
    spelling matches.
    """
    try:
        with db.db_cursor() as cur:
            cur.execute("SELECT url FROM seen_links")
            hostnames = set()
            for (url,) in cur.fetchall():
                host = (urlparse(url).hostname or "").lower()
                if not host:
                    continue
                hostnames.add(host)
                hostnames.add(host[4:] if host.startswith("www.") else f"www.{host}")
            return hostnames
    except Exception as e:
        logger.error("crt_monitor: failed to load seen hostnames: %s", e)
        return set()
