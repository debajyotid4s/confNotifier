import logging

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .constants import MAX_PAGE_TEXT_CHARS, MIN_PAGE_TEXT_CHARS
from .scroll import _human_like_scroll
from .url import _normalize_url

logger = logging.getLogger(__name__)


def fetch_page_text_impl(mgr, url: str, timeout: int = 30000,
                         wait_until: str = "domcontentloaded") -> str | None:
    """Load a URL and return its visible text, up to MAX_PAGE_TEXT_CHARS."""
    if not mgr._page:
        logger.error("PlaywrightManager: browser not initialized")
        return None
    with mgr._page_lock:
        url = _normalize_url(url)
        for attempt in range(2):
            try:
                mgr._page.goto(url, timeout=30000, wait_until=wait_until)
                _human_like_scroll(mgr._page)
                text = mgr._page.evaluate(
                    "document.body ? document.body.innerText : ''"
                )
                if not text or len(text.strip()) < MIN_PAGE_TEXT_CHARS:
                    return None
                return text[:MAX_PAGE_TEXT_CHARS]
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
                        text = mgr._page.evaluate(
                            "document.body ? document.body.innerText : ''"
                        )
                        if text and len(text.strip()) >= MIN_PAGE_TEXT_CHARS:
                            return text[:MAX_PAGE_TEXT_CHARS]
                    except Exception:
                        pass
                    return None
                logger.warning("PlaywrightManager: error loading %s: %s", url, e)
                return None
    return None
