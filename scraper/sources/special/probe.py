"""Probe helpers shared by the special-source handlers.

All sources come from the unified ``config/sources.json`` (via
:mod:`scraper.sources.config`). Bodies are fetched cheapest-first —
plain ``requests``, then the ``curl`` binary, then the Playwright stealth
browser — via :class:`TieredProbe`, which escalates while bodies fail
verification, not just on fetch failure (a 200 carrying a challenge shell
is a miss, not a page).
"""

import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from scraper.sources.config import load_sources
from scraper.sources.homepage_links.fetch_curl import _fetch_curl
from scraper.sources.homepage_links.fetch_playwright import _fetch_playwright
from scraper.utils import is_safe_url

from .constants import CURL_MIN_CONTENT, MIN_CONTENT, PROBE_TIMEOUT, USER_AGENT

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


def _curl_body(url: str) -> str | None:
    """curl tier (reuses the homepage scanner's binary fallback)."""
    try:
        body = _fetch_curl(url)
    except Exception as e:
        logger.debug("probe: curl tier failed for %s: %s", url, e)
        return None
    return body if body and len(body) > CURL_MIN_CONTENT else None


def _playwright_body(url: str, playwright) -> str | None:
    """Playwright tier (renders JS shells that requests/curl only see as stubs)."""
    try:
        return _fetch_playwright(url, playwright)
    except Exception as e:
        logger.debug("probe: playwright tier failed for %s: %s", url, e)
        return None


class TieredProbe:
    """Verify-aware transport escalation: requests → curl → Playwright.

    Cheapest tier first; escalates while fetched bodies fail verification,
    not just when a fetch returns nothing. Bodies are cached per URL so a
    year re-check never re-spends a request.

    The curl/playwright tiers engage only when a live browser is attached
    (production runs). Callers injecting ``fetch`` without one — unit tests
    included — stay single-tier and offline-safe.
    """

    def __init__(self, fetch=None, playwright=None, verify: bool = True) -> None:
        self._verify = verify
        self._chain = [fetch or _fetch_text]
        if playwright is not None:
            self._chain += [_curl_body, lambda url: _playwright_body(url, playwright)]
        self._cache: dict[str, dict] = {}
        #: Number of fetched bodies (any tier) seen so far — distinguishes
        #: "site unreachable" from "reachable but wrong edition".
        self.bodies_seen = 0

    @property
    def primary(self):
        """The cheap first-tier fetch (injected or requests)."""
        return self._chain[0]

    def raw(self, url: str) -> str | None:
        """Best raw body across tiers (first non-empty wins), cached."""
        entry = self._cache.setdefault(url, {"bodies": [], "i": 0})
        while entry["i"] < len(self._chain):
            func = self._chain[entry["i"]]
            entry["i"] += 1
            try:
                body = func(url)
            except Exception as e:
                logger.debug("probe: tier failed for %s: %s", url, e)
                continue
            if body:
                entry["bodies"].append(body)
                self.bodies_seen += 1
                return body
        return entry["bodies"][0] if entry["bodies"] else None

    def verified(self, url: str, year: int, prev: int | None) -> str | None:
        """First body verifying as ``year``, escalating tiers as needed."""
        entry = self._cache.setdefault(url, {"bodies": [], "i": 0})
        while True:
            for body in entry["bodies"]:
                if not self._verify or verify_year_is_current(body, year, prev):
                    return body
            if entry["i"] >= len(self._chain):
                return None
            func = self._chain[entry["i"]]
            entry["i"] += 1
            try:
                body = func(url)
            except Exception as e:
                logger.debug("probe: tier failed for %s: %s", url, e)
                continue
            if body:
                entry["bodies"].append(body)
                self.bodies_seen += 1


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
    fetch_candidates=None,
) -> str | None:
    """Tier-3 discovery: crawl the homepage for any link carrying the target year.

    Pattern-agnostic — catches a URL structure change the static candidate
    list never anticipated. ``fetch(url)`` returns HTML or None. Returns the
    first verified URL, or None. ``fetch_candidates`` (default: ``fetch``)
    fetches the discovered links — pass a cheaper single-tier fetch to bound
    escalation cost; the homepage itself always deserves the full chain.
    """
    fetch_candidates = fetch_candidates or fetch
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
            body = fetch_candidates(url)
        except Exception:
            continue
        if body and verify_year_is_current(body, target_year, previous_year):
            found.claim(url)
            logger.info("special/discovery: %s → new candidate (via homepage links)", url)
            return url
    return None
