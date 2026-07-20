import logging
import random
import time
import threading
from urllib.parse import urlparse, urlunparse, quote, unquote

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


class PlaywrightManager:
    """Singleton Playwright browser manager — one Chromium instance for the entire run.

    Usage:
        with PlaywrightManager() as pw:
            text = pw.fetch_page_text(url)
            html = pw.fetch_page_html(url)
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._page_lock = threading.Lock()

    def __enter__(self):
        if self._page is not None:
            return self
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            user_agent = random.choice(USER_AGENTS)
            self._context = self._browser.new_context(
                user_agent=user_agent,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            Stealth().apply_stealth_sync(self._context)
            self._page = self._context.new_page()
            logger.info("PlaywrightManager: Chromium launched with stealth")
            return self
        except Exception as e:
            logger.critical("PlaywrightManager: failed to launch browser: %s", e)
            self.close()
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Gracefully shut down browser and Playwright."""
        try:
            if self._page and not self._page.is_closed():
                self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None
        self._initialized = False
        logger.info("PlaywrightManager: browser closed")

    def _is_alive(self) -> bool:
        """Check if the browser process is still responsive."""
        try:
            self._page.evaluate("1 + 1")
            return True
        except Exception:
            return False

    def _restart(self):
        """Close and relaunch the browser. Called when crash is detected."""
        logger.warning("PlaywrightManager: restarting browser after crash")
        # Clean up internal state without destroying the singleton reference
        try:
            if self._page and not self._page.is_closed():
                self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None
        # Relaunch — __enter__ checks _page is None, so it will re-init
        self.__enter__()

    def _normalize_url(self, url: str) -> str:
        """Percent-encode special chars (spaces, unicode, etc.) in the URL path
        without double-encoding already-encoded sequences."""
        try:
            parsed = urlparse(url)
            path = quote(unquote(parsed.path), safe="/:@!$&'()*+,;=-._~%")
            query = quote(unquote(parsed.query), safe="&=")
            return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, query, parsed.fragment))
        except Exception:
            return url

    def _human_like_scroll(self):
        """Inject small randomized scroll to mimic human behavior."""
        steps = random.randint(3, 5)
        for _ in range(steps):
            try:
                self._page.evaluate(
                    "window.scrollTo({top: Math.random()*500, behavior: 'smooth'})"
                )
                time.sleep(random.uniform(0.3, 0.8))
            except Exception:
                break

    def fetch_page_text(self, url: str, timeout: int = 30000) -> str | None:
        """Load a URL and return visible text (first 8000 chars).

        Uses networkidle for automatic wait — no arbitrary sleep needed.
        Applies human-like scroll after load for stealth.
        Auto-restarts browser on crash, retries once.
        Returns None on any error.
        """
        if not self._page:
            logger.error("PlaywrightManager: browser not initialized")
            return None

        with self._page_lock:
            url = self._normalize_url(url)
            for attempt in range(2):
                try:
                    self._page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    self._human_like_scroll()
                    text = self._page.evaluate("document.body.innerText")
                    if not text or len(text.strip()) < 50:
                        return None
                    return text[:8000]
                except PlaywrightTimeout:
                    logger.warning("PlaywrightManager: timeout loading %s", url)
                    return None
                except Exception as e:
                    if attempt == 0 and not self._is_alive():
                        logger.error("PlaywrightManager: browser crashed on %s, restarting", url)
                        try:
                            self._restart()
                            continue
                        except Exception as restart_err:
                            logger.critical("PlaywrightManager: restart failed: %s", restart_err)
                            return None
                    logger.warning("PlaywrightManager: error loading %s: %s", url, e)
                    return None
        return None

    def fetch_page_html(self, url: str, timeout: int = 30000) -> str | None:
        """Load a URL and return full HTML source.

        Used by homepage_links.py for regex-based link scanning.
        Auto-restarts browser on crash, retries once.
        Returns None on any error.
        """
        if not self._page:
            logger.error("PlaywrightManager: browser not initialized")
            return None

        with self._page_lock:
            url = self._normalize_url(url)
            for attempt in range(2):
                try:
                    self._page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    self._human_like_scroll()
                    html = self._page.content()
                    if not html or len(html.strip()) < 50:
                        return None
                    return html
                except PlaywrightTimeout:
                    logger.warning("PlaywrightManager: timeout loading %s", url)
                    return None
                except Exception as e:
                    if attempt == 0 and not self._is_alive():
                        logger.error("PlaywrightManager: browser crashed on %s, restarting", url)
                        try:
                            self._restart()
                            continue
                        except Exception as restart_err:
                            logger.critical("PlaywrightManager: restart failed: %s", restart_err)
                            return None
                    logger.warning("PlaywrightManager: error loading %s: %s", url, e)
                    return None
        return None
