"""Discovery source: certificate transparency logs.

A university brings up `icxyz2027.univ.ac.bd`, and a TLS certificate is issued
for it days or weeks before anything links to it. Watching CT logs therefore
finds conferences earlier than homepage scanning, and finds the ones no homepage
ever links.

CertSpotter is the primary feed because it supports an `after` cursor, so each
run only reads issuances newer than the last one. crt.sh is the fallback when
CertSpotter has nothing or errors — it has no cursor and is slow, hence the
generous timeout.

Runs once a day from send_reminders.py rather than on every scraper pass:
certificates do not churn within hours.
"""

import json
import logging
import os
import time
from urllib.parse import urlparse

import requests
from psycopg2.extras import execute_values

from scraper import db
from scraper.patterns import is_conference_hostname

logger = logging.getLogger(__name__)

#: Domains queried per run. CertSpotter's free tier is metered, and unscanned
#: domains are prioritised so coverage advances every day.
MAX_QUERIES_PER_RUN = 8
CERTSPOTTER_URL = "https://api.certspotter.com/v1/issuances"
CRTSH_URL = "https://crt.sh/?q=%.{domain}&output=json"
QUERY_TIMEOUT = 15
CRTSH_TIMEOUT = 60
INTER_QUERY_SLEEP = 0.2


def _load_domains() -> list[str]:
    with open("config/universities.json") as f:
        return json.load(f)


def _load_cursors() -> dict[str, int]:
    """Last processed CertSpotter issuance id per domain."""
    try:
        with db.db_cursor() as cur:
            cur.execute("SELECT domain, last_id FROM certspotter_cursor")
            return dict(cur.fetchall())
    except Exception as e:
        logger.error("crt_monitor: failed to load cursors: %s", e)
        return {}


def _save_cursors(updates: dict[str, int]) -> None:
    """Persist every advanced cursor in one round-trip."""
    if not updates:
        return
    try:
        with db.db_cursor(commit=True) as cur:
            execute_values(
                cur,
                "INSERT INTO certspotter_cursor (domain, last_id) VALUES %s "
                "ON CONFLICT (domain) DO UPDATE SET last_id = EXCLUDED.last_id",
                list(updates.items()),
                template="(%s, %s)",
            )
    except Exception as e:
        logger.error("crt_monitor: failed to save cursors: %s", e)


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


def _query_certspotter(domain: str, after_id: int | None) -> tuple[list[str], int | None, bool]:
    """Fetch new issuances for a domain.

    Returns (dns_names, new_cursor, rate_limited). `new_cursor` is None when the
    query failed in a way that should trigger the crt.sh fallback, and 0 when the
    domain simply has nothing new.
    """
    params = {"domain": domain, "include_subdomains": "true", "match_wildcards": "true"}
    if after_id:
        params["after"] = after_id

    key = os.environ["CERTSPOTTER_API_KEY"]
    resp = requests.get(CERTSPOTTER_URL, params=params,
                        headers={"Authorization": f"Bearer {key}"}, timeout=QUERY_TIMEOUT)

    if resp.status_code == 429:
        logger.warning("certspotter: rate limited on %s", domain)
        return [], None, True
    if resp.status_code == 404:
        return [], 0, False
    if resp.status_code != 200:
        logger.warning("certspotter: HTTP %d for %s", resp.status_code, domain)
        return [], None, False

    try:
        data = resp.json()
    except ValueError:
        logger.warning("certspotter: non-JSON response for %s", domain)
        return [], None, False
    if not data:
        return [], 0, False

    dns_names: list[str] = []
    last_id = 0
    for item in data:
        try:
            item_id = item["id"]
        except (KeyError, TypeError):
            continue
        last_id = max(last_id, item_id)
        dns_names.extend(name.strip().lower() for name in item.get("dns_names", []))

    return dns_names, last_id, False


def _crtsh_fallback(domain: str) -> list[str]:
    """Read every certificate name for a domain from crt.sh."""
    try:
        resp = requests.get(CRTSH_URL.format(domain=domain), timeout=CRTSH_TIMEOUT,
                            headers={"User-Agent": "curl/8.0"})
        if resp.status_code != 200:
            return []
        names = []
        for entry in resp.json():
            for raw in entry.get("name_value", "").split("\n"):
                cleaned = raw.strip().lower().lstrip("*.")
                if cleaned:
                    names.append(cleaned)
        return names
    except Exception as e:
        logger.warning("crtsh fallback failed for %s: %s", domain, e)
        return []


def _batch_for_this_run(all_domains: list[str], cursors: dict) -> list[str]:
    """Pick which domains to query, unscanned ones first."""
    unscanned = [d for d in all_domains if d not in cursors]
    scanned = [d for d in all_domains if d in cursors]
    return (unscanned + scanned)[:MAX_QUERIES_PER_RUN]


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
