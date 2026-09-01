import logging

from bs4 import BeautifulSoup

from scraper.utils import is_safe_url

from .constants import FETCH_TIERS
from .fetch_curl import _fetch_curl
from .fetch_playwright import _fetch_playwright
from .fetch_requests import _fetch_requests

logger = logging.getLogger(__name__)


def _fetch(tier: str, url: str, playwright) -> str | None:
    if tier == "requests":
        return _fetch_requests(url)
    if tier == "curl":
        return _fetch_curl(url)
    if tier == "playwright":
        return _fetch_playwright(url, playwright)
    return None


def fetch_homepage(url: str, playwright=None, from_tier: str = "requests"):
    """Try each fetch tier from `from_tier` onward.

    Returns (soup, tier) or (None, None). Starting at a cached tier skips the
    tiers already known not to work for this domain.
    """
    if not is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return None, None
    start = FETCH_TIERS.index(from_tier) if from_tier in FETCH_TIERS else 0
    for tier in FETCH_TIERS[start:]:
        html = _fetch(tier, url, playwright)
        if html and len(html.strip()) > 50:
            return BeautifulSoup(html, "lxml"), tier
    return None, None


def _url_variants(domain: str, preferred: str | None = None) -> list[str]:
    """Candidate homepage URLs for a domain, preferred one first.

    Some hosts only answer on `www.`, others only on the bare domain.
    """
    variants = [f"https://www.{domain}", f"https://{domain}"]
    if preferred:
        variants = [preferred] + [v for v in variants if v != preferred]
    seen, ordered = set(), []
    for variant in variants:
        if variant not in seen:
            seen.add(variant)
            ordered.append(variant)
    return ordered


def _load_domain(domain: str, cached, playwright):
    """Load one homepage, honouring the cached tier. Returns (soup, url, tier)."""
    cached_tier, cached_url = cached if cached else (None, None)
    from_tier = cached_tier if cached_tier in FETCH_TIERS else "requests"
    for url in _url_variants(domain, cached_url):
        soup, tier = fetch_homepage(url, playwright=playwright, from_tier=from_tier)
        if soup is not None:
            return soup, url, tier
        # A cached tier that no longer works should not block the lower tiers
        # on the alternate URL variant.
        from_tier = "requests"
    return None, None, None
