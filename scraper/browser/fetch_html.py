import logging

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .scroll import _human_like_scroll
from .url import _normalize_url

logger = logging.getLogger(__name__)


def fetch_page_html_impl(mgr, url: str, timeout: int = 30000) -> str | None:
    """Load a URL and return full HTML source."""
    if not mgr._page:
        logger.error("PlaywrightManager: browser not initialized")
        return None
    with mgr._page_lock:
        url = _normalize_url(url)
        for attempt in range(2):
            try:
                mgr._page.goto(url, timeout=30000, wait_until="domcontentloaded")
                _human_like_scroll(mgr._page)
                html = mgr._page.content()
                if not html or len(html.strip()) < 50:
                    return None
                return html
            except PlaywrightTimeout:
                logger.warning("PlaywrightManager: timeout loading %s", url)
                return None
            except Exception as e:
                err_msg = str(e)
                if attempt == 0 and not mgr._is_alive():
                    logger.error(
                        "PlaywrightManager: browser crashed on %s, restarting", url
                    )
                    try:
                        mgr._restart()
                        continue
                    except Exception as re:
                        logger.critical("PlaywrightManager: restart failed: %s", re)
                        return None
                if attempt == 0 and "Execution context was destroyed" in err_msg:
                    logger.warning(
                        "PlaywrightManager: page navigated after load on %s, retrying",
                        url,
                    )
                    try:
                        mgr._page.wait_for_load_state("networkidle", timeout=15000)
                        html = mgr._page.content()
                        if html and len(html.strip()) >= 50:
                            return html
                    except Exception:
                        pass
                    return None
                logger.warning("PlaywrightManager: error loading %s: %s", url, e)
                return None
    return None
