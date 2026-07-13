import json
import logging
import re
import socket
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from db import get_connection, save_seen_link
from scraper.sources.homepage_links import _is_safe_url

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


def _load_sources(path="config/special_sources.json"):
    with open(path) as f:
        return json.load(f)


def _is_seen(url):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM seen_links WHERE url = %s", (url,))
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception as e:
        logger.error("_is_seen error: %s", e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _probe_url(url, timeout=10):
    if not _is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return False
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        return resp.status_code == 200 and len(resp.text) > 500
    except requests.RequestException as e:
        logger.debug("Probe failed for %s: %s", url, e)
    return False


# ── Handler: "path" (ICCIT-style: probe /YYYY/home/ then /YYYY/) ──


def _handle_path(source):
    base_url = source["base_url"].rstrip("/")
    year = datetime.now().year
    candidates = []

    for y in [str(year), str(year + 1)]:
        url = None
        for candidate in [f"{base_url}/{y}/home/", f"{base_url}/{y}/"]:
            if _is_seen(candidate):
                break  # already known — don't also try the fallback
            if _probe_url(candidate):
                url = candidate
                break
        if url is None:
            continue
        save_seen_link(url, source="special")
        candidates.append(url)
        logger.info("special/path: new URL found: %s", url)

    return candidates


# ── Handler: "root_year" (QPAIN-style: detect year from page content) ──


def _handle_root_year(source):
    base_url = source["base_url"]
    year = datetime.now().year
    candidates = []

    if not _is_safe_url(base_url):
        logger.warning("SSRF blocked: %s", base_url)
        return []

    try:
        resp = requests.get(
            base_url,
            timeout=10,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        if resp.status_code != 200 or len(resp.text) < 500:
            logger.warning("special/root_year: %s unreachable, skipping", base_url)
            return []
    except requests.RequestException as e:
        logger.warning("special/root_year: %s unreachable: %s", base_url, e)
        return []

    # Extract edition year from page content
    soup = BeautifulSoup(resp.text, "lxml")
    search_text = ""
    title_tag = soup.find("title")
    if title_tag:
        search_text = title_tag.get_text()
    if not search_text:
        h1_tag = soup.find("h1")
        if h1_tag:
            search_text = h1_tag.get_text()
    if not search_text:
        search_text = soup.get_text(separator=" ", strip=True)[:2000]

    found_year = None
    for match in re.finditer(r"\b(\d{4})\b", search_text):
        candidate_year = int(match.group(1))
        if year <= candidate_year <= year + 2:
            found_year = candidate_year
            break

    if found_year is None:
        logger.warning("special/root_year: no year found in %s, skipping", base_url)
        return []

    # Dedup key: "https://qpain.org#2026"
    dedup_key = f"{base_url}#{found_year}"

    if _is_seen(dedup_key):
        return []

    save_seen_link(dedup_key, source="special")
    candidates.append(base_url)
    logger.info("special/root_year: new edition detected — %s (%d)", base_url, found_year)

    return candidates


def _resolves(url: str) -> bool:
    """Return True if the hostname resolves via DNS."""
    try:
        hostname = urlparse(url).hostname
        socket.getaddrinfo(hostname, None)
        return True
    except socket.gaierror:
        return False


def _already_seen(url: str, conn) -> bool:
    """Return True if url exists in seen_links with any status."""
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM seen_links WHERE url = %s", (url,))
    exists = cur.fetchone() is not None
    cur.close()
    return exists


def _handle_subdomain_probe(source):
    base_domain = source.get("base_domain", "")
    known_prefixes = source.get("known_prefixes", [])
    probe_years = source.get("probe_years", [])
    candidates = []

    conn = None
    try:
        conn = get_connection()
        for prefix in known_prefixes:
            urls = []
            for year in probe_years:
                urls.append(f"https://{prefix}{year}.{base_domain}")
            urls.append(f"https://{prefix}.{base_domain}")

            for candidate in urls:
                if _already_seen(candidate, conn):
                    logger.info(
                        "subdomain_probe: %s → already seen, skipping",
                        candidate
                    )
                    continue
                resolves = _resolves(candidate)
                logger.info(
                    "subdomain_probe: checking %s — resolves=%s",
                    candidate, resolves
                )
                if resolves and _probe_url(candidate):
                    candidates.append(candidate)
                    save_seen_link(candidate, source="special", status="pending")
                    logger.info(
                        "subdomain_probe: %s → new candidate", candidate
                    )
    except Exception as e:
        logger.error(
            "subdomain_probe error for %s: %s", base_domain, e
        )
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return candidates


# ── Dispatcher ──

_HANDLERS = {
    "path": _handle_path,
    "root_year": _handle_root_year,
    "subdomain_probe": _handle_subdomain_probe,
}


def run():
    sources = _load_sources()
    candidates = []

    for source in sources:
        source_type = source.get("type")
        handler = _HANDLERS.get(source_type)
        if handler is None:
            logger.warning("special: unknown source type '%s', skipping", source_type)
            continue
        candidates.extend(handler(source))

    logger.info("special: found %d new special source URLs", len(candidates))
    return candidates
