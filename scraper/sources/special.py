"""Discovery source: curated conference sites with known URL shapes.

Homepage scanning misses conferences whose university never links them. These
handlers go straight at the known sites:

  path            probe /{year}/ and /{year}/home/ (or explicit templates)
  root_year       read the edition year off the landing page
  subdomain_probe resolve prefix+year subdomains via DNS before any HTTP
  conf_info_bd    scrape the community-maintained conference table

The set of already-seen URLs is loaded once per run; every handler tests it in
memory instead of issuing a SELECT per probe.
"""

import json
import logging
import re
import socket
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from scraper import db
from scraper.dedup import canonical_url
from scraper.utils import is_safe_url

logger = logging.getLogger(__name__)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

PROBE_TIMEOUT = 10
#: Minimum body size for a probe to count as a real page. Single-page apps ship
#: a small HTML shell, so path handlers lower this.
MIN_CONTENT = 500
MIN_CONTENT_SPA = 200


def _load_sources(path="config/special_sources.json") -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _probe_url(url: str, timeout: int = PROBE_TIMEOUT, min_content: int = MIN_CONTENT) -> bool:
    """True when the URL responds 200 with a body worth extracting."""
    if not is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return False
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT},
                            allow_redirects=True)
        return resp.status_code == 200 and len(resp.text) > min_content
    except requests.RequestException as e:
        logger.debug("Probe failed for %s: %s", url, e)
    return False


def _resolves(url: str) -> bool:
    """True when the hostname has a DNS record — cheaper than an HTTP probe."""
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        socket.getaddrinfo(hostname, None)
        return True
    except (socket.gaierror, UnicodeError):
        return False


class Discovery:
    """Accumulates candidates for one run and dedups them against seen_links.

    Handlers call `claim()`; the caller persists everything in one batch at the
    end. This replaces a per-URL SELECT plus a per-URL INSERT.
    """

    def __init__(self, seen: set[str]) -> None:
        # Compare canonically so /2027 and /2027/home/ are not probed twice.
        self._seen = {canonical_url(u) for u in seen}
        self.candidates: list[str] = []
        self.rows: list[tuple[str, str, str]] = []

    def is_new(self, url: str) -> bool:
        return canonical_url(url) not in self._seen

    def claim(self, url: str, status: str = "pending") -> None:
        """Record a newly discovered URL."""
        key = canonical_url(url)
        if key in self._seen:
            return
        self._seen.add(key)
        self.candidates.append(url)
        self.rows.append((url, "special", status))

    def claim_untracked(self, url: str) -> None:
        """Record a candidate without writing it to seen_links.

        Used by root_year, whose freshness is decided against the conferences
        table so a failed extraction does not permanently block the edition.
        """
        self.candidates.append(url)


# ── Handler: path ─────────────────────────────────────────────────────────────

def _handle_path(source: dict, found: Discovery) -> None:
    """Probe year-based paths under a known conference domain."""
    base_url = source["base_url"].rstrip("/")
    year = datetime.now().year
    probe_years = source.get("probe_years", [year, year + 1])

    custom_paths = source.get("paths")
    if custom_paths:
        for y in probe_years:
            for template in custom_paths:
                url = base_url + template.replace("{year}", str(y))
                if not found.is_new(url):
                    continue
                if _probe_url(url, min_content=MIN_CONTENT_SPA):
                    found.claim(url)
                    logger.info("special/path: new URL found: %s", url)
        return

    path_cache = db.load_special_path_cache()
    cached_entry = path_cache.get(base_url)
    cached_pattern = cached_entry[1] if cached_entry else None

    for y in probe_years:
        # Try the pattern that worked last time first.
        if cached_pattern:
            cached_url = cached_pattern.replace("{year}", str(y))
            if found.is_new(cached_url) and _probe_url(cached_url):
                found.claim(cached_url)
                logger.info("special/path (cached): new URL found: %s", cached_url)
                continue

        # Probe every shape. The previous implementation used `break` here, so a
        # single already-seen candidate silently skipped the remaining patterns
        # for that year.
        for candidate in (f"{base_url}/{y}/home/", f"{base_url}/{y}/"):
            if not found.is_new(candidate):
                continue
            if not _probe_url(candidate):
                continue
            found.claim(candidate)
            logger.info("special/path: new URL found: %s", candidate)
            pattern = candidate.replace(f"/{y}/", "/{year}/")
            db.save_special_path_cache(base_url, y, pattern)
            cached_pattern = pattern
            break


# ── Handler: root_year ────────────────────────────────────────────────────────

def _is_edition_in_db(base_url: str, year: int) -> bool:
    """True when a conference at this URL already exists for this year."""
    try:
        with db.db_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM conferences WHERE website = %s "
                "AND date_start >= %s AND date_start < %s LIMIT 1",
                (db.normalize_website(base_url), f"{year}-01-01", f"{year + 1}-01-01"),
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.error("_is_edition_in_db error: %s", e)
        return False


def _handle_root_year(source: dict, found: Discovery) -> None:
    """Read the advertised edition year off a conference landing page."""
    base_url = source["base_url"]
    year = datetime.now().year

    if not is_safe_url(base_url):
        logger.warning("SSRF blocked: %s", base_url)
        return

    try:
        resp = requests.get(base_url, timeout=PROBE_TIMEOUT,
                            headers={"User-Agent": USER_AGENT}, allow_redirects=True)
        if resp.status_code != 200 or len(resp.text) < MIN_CONTENT:
            logger.warning("special/root_year: %s unreachable, skipping", base_url)
            return
    except requests.RequestException as e:
        logger.warning("special/root_year: %s unreachable: %s", base_url, e)
        return

    soup = BeautifulSoup(resp.text, "lxml")
    search_text = ""
    for finder in (lambda: soup.find("title"), lambda: soup.find("h1")):
        tag = finder()
        if tag and tag.get_text(strip=True):
            search_text = tag.get_text()
            break
    if not search_text:
        search_text = soup.get_text(separator=" ", strip=True)[:2000]

    found_year = next(
        (y for y in (int(m.group(1)) for m in re.finditer(r"\b(\d{4})\b", search_text))
         if year <= y <= year + 2),
        None,
    )
    if found_year is None:
        logger.warning("special/root_year: no edition year found in %s, skipping", base_url)
        return

    if _is_edition_in_db(base_url, found_year):
        logger.info("special/root_year: edition %d already saved, skipping — %s",
                    found_year, base_url)
        return

    found.claim_untracked(f"root_year:{found_year}:{base_url}")
    logger.info("special/root_year: new edition detected — %s (%d)", base_url, found_year)


# ── Handler: subdomain_probe ──────────────────────────────────────────────────

def _handle_subdomain_probe(source: dict, found: Discovery) -> None:
    """Resolve known conference subdomain prefixes before spending an HTTP call."""
    base_domain = source.get("base_domain", "")
    if not base_domain:
        return

    for prefix in source.get("known_prefixes", []):
        urls = [f"https://{prefix}{year}.{base_domain}" for year in source.get("probe_years", [])]
        urls.append(f"https://{prefix}.{base_domain}")

        for candidate in urls:
            if not found.is_new(candidate):
                continue
            if not _resolves(candidate):
                continue
            if _probe_url(candidate):
                found.claim(candidate)
                logger.info("subdomain_probe: %s → new candidate", candidate)


# ── Handler: conf_info_bd ─────────────────────────────────────────────────────

def _handle_conf_info_bd(source: dict, found: Discovery) -> None:
    """Scrape the conference table at conf.info.bd.

    Each data row links out to the conference website via <a class="conf-link">.
    """
    url = source.get("url", "https://conf.info.bd")
    logger.info("conf_info_bd: fetching %s", url)

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            logger.error("conf_info_bd: HTTP %d from %s", resp.status_code, url)
            return
    except requests.RequestException as e:
        logger.error("conf_info_bd: request failed for %s: %s", url, e)
        return

    soup = BeautifulSoup(resp.text, "lxml")
    before = len(found.candidates)
    for link in soup.select("a.conf-link"):
        href = (link.get("href") or "").strip()
        if not href or not found.is_new(href):
            continue
        if not is_safe_url(href):
            logger.warning("conf_info_bd: SSRF blocked: %s", href)
            continue
        found.claim(href)
        logger.info("conf_info_bd: new URL found: %s", href)

    logger.info("conf_info_bd: found %d new candidate(s)", len(found.candidates) - before)


_HANDLERS = {
    "path": _handle_path,
    "root_year": _handle_root_year,
    "subdomain_probe": _handle_subdomain_probe,
    "conf_info_bd": _handle_conf_info_bd,
}


def run() -> list[str]:
    """Run every configured special source and return new candidate URLs."""
    found = Discovery(db.load_seen_urls())

    for source in _load_sources():
        handler = _HANDLERS.get(source.get("type"))
        if handler is None:
            logger.warning("special: unknown source type '%s', skipping", source.get("type"))
            continue
        try:
            handler(source, found)
        except Exception as e:
            logger.error("special: handler %s failed for %s: %s",
                         source.get("type"), source.get("base_url") or source.get("url"), e)

    if found.rows:
        db.save_seen_links_bulk(found.rows)

    logger.info("special: found %d new special source URL(s)", len(found.candidates))
    return found.candidates
