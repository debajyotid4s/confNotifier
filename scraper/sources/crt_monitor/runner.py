import logging
import os
import time

import requests

from scraper import db
from scraper.patterns import is_conference_hostname

from .batch import _batch_for_this_run, _load_domains
from .certspotter import _query_certspotter
from .constants import INTER_QUERY_SLEEP
from .crtsh import _crtsh_fallback
from .cursors import _load_cursors, _save_cursors
from .hosts import _load_seen_hostnames

logger = logging.getLogger(__name__)


def run() -> list[str]:
    """Query CT logs for new conference hostnames. Returns new candidate URLs."""
    if not os.environ.get("CERTSPOTTER_API_KEY"):
        logger.critical("certspotter: CERTSPOTTER_API_KEY not set")
        return []

    cursors = _load_cursors()
    seen = _load_seen_hostnames()
    batch = _batch_for_this_run(_load_domains(), cursors)

    candidates: list[str] = []
    cursor_updates: dict[str, int] = {}

    for domain in batch:
        dns_names: list[str] = []
        new_cursor: int | None = None
        try:
            dns_names, new_cursor, rate_limited = _query_certspotter(domain, cursors.get(domain))
            if rate_limited:
                logger.warning("certspotter: stopping run early after rate limit")
                break
        except requests.RequestException as e:
            logger.warning("certspotter: request error for %s: %s", domain, e)

        if dns_names:
            cursor_updates[domain] = new_cursor
        elif new_cursor is None:
            logger.info("certspotter: falling back to crt.sh for %s", domain)
            dns_names = _crtsh_fallback(domain)
        else:
            cursor_updates[domain] = 0

        for name in dns_names:
            if name in seen or not is_conference_hostname(name):
                continue
            bare = name[4:] if name.startswith("www.") else name
            if bare in seen:
                continue
            seen.add(name)
            seen.add(bare)
            candidates.append(f"https://{name}")
            logger.info("crt_monitor: new candidate -> https://%s", name)

        time.sleep(INTER_QUERY_SLEEP)

    if candidates:
        db.save_seen_links_bulk([(u, "crt_monitor", "pending") for u in candidates])
    _save_cursors(cursor_updates)

    logger.info("crt_monitor: %d new candidate(s) from %d domain(s)", len(candidates), len(batch))
    return candidates
