import json
import logging
import os
import re
import time

import requests

from db import get_connection

logger = logging.getLogger(__name__)

MAX_QUERIES_PER_RUN = 8
CERTSPOTTER_URL = "https://api.certspotter.com/v1/issuances"

KNOWN_JUNK_PATTERNS = [
    "autodiscover", "cpcontacts", "convocation", "convapi",
    "ictcell", "ictserver", "ictvm", "webdisk", "library",
    "contact", "mail", "app", "heqep", "emss", "clab", "econ",
    "info", "secondaryschool", "icpcdhaka", "icpcbd",
    "ict.", "www.ict.", "ieeecomsoc", "ieee-comsoc",
    "email", "moodle", "webmail", "vpn", "remote",
    "portal", "sis", "erp", "accounts", "admission",
    "campus", "registrar", "result", "notice",
]

CONF_PREFIXES = ["ic", "conf", "conference", "symposium", "workshop", "congress", "summit"]
CONF_KEYWORDS = [
    "ieee", "icon", "icece", "iccit", "icmiee", "icace", "icca",
    "iciset", "peeiacon", "raaicon", "spicscon", "becithcon",
    "icefront",
]


def _is_conference_subdomain(name: str) -> bool:
    lower = name.lower().lstrip("*.")
    if lower.startswith("www."):
        lower = lower[4:]
    for junk in KNOWN_JUNK_PATTERNS:
        if lower.startswith(junk):
            return False
    years = re.findall(r"(20\d{2})", lower)
    if years and max(int(y) for y in years) < 2025:
        return False
    if any(lower.startswith(p) for p in CONF_PREFIXES):
        return True
    return any(kw in lower for kw in CONF_KEYWORDS)


def _load_domains() -> list[str]:
    with open("config/universities.json") as f:
        return json.load(f)


def _load_cursors() -> dict[str, int]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT domain, last_id FROM certspotter_cursor")
        result = dict(cur.fetchall())
        cur.close()
        return result
    finally:
        conn.close()


def _save_cursor(domain: str, last_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO certspotter_cursor (domain, last_id) VALUES (%s, %s) "
            "ON CONFLICT (domain) DO UPDATE SET last_id = EXCLUDED.last_id",
            (domain, last_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("crt_monitor: failed to save cursor for %s: %s", domain, e)
    finally:
        conn.close()


def _load_seen_urls() -> set[str]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT url FROM seen_links WHERE status IN "
            "('pending', 'not_conference', 'low_confidence', 'extracted')"
        )
        result = {row[0].replace("https://", "").replace("http://", "") for row in cur.fetchall()}
        cur.close()
        return result
    finally:
        conn.close()


def _save_candidates(candidates: list[str]) -> None:
    if not candidates:
        return
    conn = get_connection()
    try:
        cur = conn.cursor()
        for url in candidates:
            cur.execute(
                "INSERT INTO seen_links (url, source, status) VALUES (%s, 'crt_monitor', 'pending') "
                "ON CONFLICT (url) DO NOTHING",
                (url,),
            )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("crt_monitor: failed to save candidates: %s", e)
        raise
    finally:
        conn.close()


def _query_certspotter(domain: str, after_id: int | None) -> tuple[list[str], int | None, bool]:
    params = {
        "domain": domain,
        "include_subdomains": "true",
        "match_wildcards": "true",
    }
    if after_id:
        params["after"] = after_id

    key = os.environ["CERTSPOTTER_API_KEY"]
    headers = {"Authorization": f"Bearer {key}"}

    resp = requests.get(CERTSPOTTER_URL, params=params, headers=headers, timeout=15)

    if resp.status_code == 429:
        logger.warning("certspotter: 429 rate limited for %s", domain)
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

    dns_names = []
    last_id = 0
    for item in data:
        try:
            item_id = item["id"]
        except (KeyError, TypeError):
            continue
        if item_id > last_id:
            last_id = item_id
        for name in item.get("dns_names", []):
            dns_names.append(name.strip().lower())

    return dns_names, last_id, False


def _crtsh_fallback(domain: str) -> list[str]:
    url = f"https://crt.sh/?q=%.{domain}&output=json"
    try:
        resp = requests.get(url, timeout=60, headers={"User-Agent": "curl/8.0"})
        if resp.status_code == 200:
            names = []
            for entry in resp.json():
                for raw in entry.get("name_value", "").split("\n"):
                    raw = raw.strip().lower().lstrip("*.")
                    if raw:
                        names.append(raw)
            return names
    except Exception as e:
        logger.warning("crtsh fallback failed for %s: %s", domain, e)
    return []


def run() -> list[str]:
    if not os.environ.get("CERTSPOTTER_API_KEY"):
        logger.critical("certspotter: CERTSPOTTER_API_KEY not set")
        return []

    all_domains = _load_domains()
    cursors = _load_cursors()
    seen = _load_seen_urls()
    candidates = []

    unscanned = [d for d in all_domains if d not in cursors]
    scanned = [d for d in all_domains if d in cursors]
    batch = (unscanned + scanned)[:MAX_QUERIES_PER_RUN]

    cursor_updates = {}
    rate_limited = False

    for domain in batch:
        if rate_limited:
            break

        after_id = cursors.get(domain)
        dns_names = []
        new_cursor = None
        is_rate_limited = False

        try:
            dns_names, new_cursor, is_rate_limited = _query_certspotter(domain, after_id)
        except requests.RequestException as e:
            logger.warning("certspotter: request error for %s: %s", domain, e)

        if is_rate_limited:
            rate_limited = True
            break

        if dns_names:
            cursor_updates[domain] = new_cursor
        elif new_cursor is None:
            logger.info("certspotter: fallback to crt.sh for %s", domain)
            dns_names = _crtsh_fallback(domain)
        else:
            cursor_updates[domain] = 0

        for name in dns_names:
            if not _is_conference_subdomain(name):
                continue
            bare = name.replace("www.", "", 1)
            if bare in seen or f"www.{bare}" in seen:
                continue
            url = f"https://{name}"
            candidates.append(url)
            seen.add(name)
            seen.add(bare)
            logger.info("crt_monitor: new candidate -> %s", url)

        time.sleep(0.2)

    _save_candidates(candidates)
    for domain, last_id in cursor_updates.items():
        _save_cursor(domain, last_id)

    logger.info("crt_monitor: %d new candidate(s) from %d domain(s)", len(candidates), len(batch))
    return candidates
