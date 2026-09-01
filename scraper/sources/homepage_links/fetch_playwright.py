import logging

from scraper.browser import PlaywrightManager
from scraper.utils import is_safe_url

logger = logging.getLogger(__name__)


def _fetch_playwright(url: str, playwright: PlaywrightManager | None) -> str | None:
    """Fetch with a stealth headless browser — clears Cloudflare JS challenges."""
    if playwright is None:
        return None
    if not is_safe_url(url):
        logger.warning("SSRF blocked (playwright): %s", url)
        return None
    try:
        return playwright.fetch_page_html(url)
    except Exception as e:
        logger.warning("Playwright fetch failed for %s: %s", url, e)
        return None
