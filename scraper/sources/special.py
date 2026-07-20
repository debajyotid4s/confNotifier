import json
import logging
import re
import socket
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from db import get_connection, save_seen_link, load_special_path_cache, save_special_path_cache
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


def _probe_url(url, timeout=10, min_content=500):
    """Probe a URL with requests. Returns True if reachable and has meaningful content.

    Args:
        url: The URL to probe.
        timeout: Request timeout in seconds.
        min_content: Minimum response body length to consider valid.
                     Use 200 for SPA pages that have a small HTML shell.
    """
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
        return resp.status_code == 200 and len(resp.text) > min_content
    except requests.RequestException as e:
        logger.debug("Probe failed for %s: %s", url, e)
    return False


# ── Handler: "conf_info_bd" (conf.info.bd HTML table scraper) ──


def _handle_conf_info_bd(source):
    """Scrape conf.info.bd's HTML table of upcoming conferences.

    The site has 3 tables (IEEE, ACM, Others). Each table row has 6 columns,
    the last being a <a class="conf-link"> with the conference website URL.
    """
    url = source.get("url", "https://conf.info.bd")
    logger.info("conf_info_bd: fetching %s", url)

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            logger.error("conf_info_bd: HTTP %d from %s", resp.status_code, url)
            return []
    except requests.RequestException as e:
        logger.error("conf_info_bd: request failed for %s: %s", url, e)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    candidates = []

    # Select all <a class="conf-link"> — this is the 6th column in each data row
    for link_tag in soup.select("a.conf-link"):
        href = link_tag.get("href", "").strip()
        if not href:
            continue
        if not _is_safe_url(href):
            logger.warning("conf_info_bd: SSRF blocked: %s", href)
            continue
        if _is_seen(href):
            continue
        save_seen_link(href, source="special")
        candidates.append(href)
        logger.info("conf_info_bd: new URL found: %s", href)

    logger.info("conf_info_bd: found %d new candidate(s) from %s", len(candidates), url)
    return candidates


# ── Handler: "path" (ICCIT-style: probe /YYYY/home/ then /YYYY/) ──
#     Enhanced to support optional "paths" and "probe_years" fields.


def _handle_path(source):
    base_url = source["base_url"].rstrip("/")
    year = datetime.now().year
    candidates = []

    # Use provided probe_years or default to current year and next
    probe_years = source.get("probe_years", [year, year + 1])

    # Use provided paths or default to standard year-based patterns
    custom_paths = source.get("paths")
    if custom_paths:
        # Explicit path templates with {year} placeholder — probe exactly these
        for y in probe_years:
            for path_template in custom_paths:
                probe_url = base_url + path_template.replace("{year}", str(y))
                if _is_seen(probe_url):
                    continue
                # SPAs (React) often have small HTML shells — use 200-byte threshold
                if _probe_url(probe_url, min_content=200):
                    save_seen_link(probe_url, source="special")
                    candidates.append(probe_url)
                    logger.info("special/path: new URL found: %s", probe_url)
        return candidates

    # Original behavior: probe /{year}/home/ and /{year}/
    path_cache = load_special_path_cache()
    cached_entry = path_cache.get(base_url)
    _, cached_pattern = cached_entry if cached_entry else (None, None)

    for y in [str(y) for y in probe_years]:
        patterns = [f"{base_url}/{y}/home/", f"{base_url}/{y}/"]

        if cached_pattern:
            cached_url = cached_pattern.replace("{year}", str(y))
            if not _is_seen(cached_url) and _probe_url(cached_url):
                save_seen_link(cached_url, source="special")
                candidates.append(cached_url)
                logger.info("special/path (cached): new URL found: %s", cached_url)
                continue
            cached_pattern = None

        url = None
        for candidate in patterns:
            if _is_seen(candidate):
                break
            if _probe_url(candidate):
                url = candidate
                break
        if url is None:
            continue
        save_seen_link(url, source="special")
        candidates.append(url)
        logger.info("special/path: new URL found: %s", url)
        pattern_template = url.replace(f"/{y}/", "/{year}/")
        save_special_path_cache(base_url, y, pattern_template)
        cached_pattern = pattern_template

    return candidates


# ── Handler: "root_year" (QPAIN-style: detect year from page content) ──


def _is_edition_in_db(base_url: str, year: int) -> bool:
    """Return True if a conference with this website + year is already saved."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM conferences "
            "WHERE website = %s "
            "  AND date_start >= %s "
            "  AND date_start < %s",
            (base_url, f"{year}-01-01", f"{year + 1}-01-01")
        )
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception as e:
        logger.error("_is_edition_in_db error: %s", e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


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

    # Check if this edition already exists in the conferences table
    # (more reliable than seen_links — a failed extraction won't block retries)
    if _is_edition_in_db(base_url, found_year):
        logger.info(
            "special/root_year: edition %d already in DB, skipping — %s",
            found_year, base_url
        )
        return []

    candidates.append(f"root_year:{found_year}:{base_url}")
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
    "conf_info_bd": _handle_conf_info_bd,
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
