"""Probe helpers shared by the special-source handlers.

All sources come from the unified ``config/sources.json`` (via
:mod:`scraper.sources.config`). Bodies are fetched with plain ``requests``
for speed; the Playwright stealth browser is reserved for the extraction
phase and the headless link check.
"""

import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from scraper.sources.config import load_sources
from scraper.utils import is_safe_url

from .constants import MIN_CONTENT, PROBE_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _load_sources(path: str | None = None) -> list[dict]:
    """Non-``regular`` entries from the unified sources config."""
    sources = load_sources(path) if path else load_sources()
    return [s for s in sources if s.get("type") in ("path_probe", "subdomain_probe", "conf_info_bd")]


def _fetch_text(url: str, timeout: int = PROBE_TIMEOUT) -> str | None:
    """GET a URL, returning body text when it is a real page (else None)."""
    if not is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return None
    try:
        resp = requests.get(
            url, timeout=timeout, headers={"User-Agent": USER_AGENT}, allow_redirects=True
        )
        if resp.status_code != 200 or len(resp.text) <= MIN_CONTENT:
            return None
        return resp.text
    except requests.RequestException as e:
        logger.debug("Probe failed for %s: %s", url, e)
    return None


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


def verify_year_is_current(content: str | None, target_year: int, previous_year: int | None = None) -> bool:
    """Stronger than a bare substring check.

    A stale page can mention next year's number once, incidentally (a footer
    copyright range, an offhand deadline note). A page genuinely updated for
    that year features it far more prominently. Either signal suffices:
    1. the year appears in <title> — a title reliably reflects the edition;
    2. the year outnumbers the previous known year's mentions in the body.
    """
    if not content:
        return False
    title_match = _TITLE_RE.search(content)
    if title_match and str(target_year) in title_match.group(1):
        return True
    target_count = content.count(str(target_year))
    if target_count == 0:
        return False
    if previous_year is None:
        return True
    return target_count >= content.count(str(previous_year))


def discover_year_links(
    base_url: str,
    target_year: int,
    fetch,
    found,
    previous_year: int | None = None,
    max_fetches: int = 10,
) -> str | None:
    """Tier-3 discovery: crawl the homepage for any link carrying the target year.

    Pattern-agnostic — catches a URL structure change the static candidate
    list never anticipated. ``fetch(url)`` returns HTML or None. Returns the
    first verified URL, or None.
    """
    base = (base_url or "").rstrip("/")
    if not base:
        return None
    try:
        home = fetch(base)
    except Exception as e:
        logger.debug("discovery: homepage fetch failed for %s: %s", base, e)
        return None
    if not home:
        return None
    try:
        soup = BeautifulSoup(home, "lxml")
    except Exception:
        return None
    fetches = 0
    for anchor in soup.find_all("a", href=True):
        href = (anchor["href"] or "").strip()
        if not href or str(target_year) not in href:
            continue
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = href if href.startswith("http") else urljoin(base + "/", href)
        if not found.is_new(url) or not is_safe_url(url):
            continue
        if fetches >= max_fetches:
            break
        fetches += 1
        try:
            body = fetch(url)
        except Exception:
            continue
        if body and verify_year_is_current(body, target_year, previous_year):
            found.claim(url)
            logger.info("special/discovery: %s → new candidate (via homepage links)", url)
            return url
    return None
