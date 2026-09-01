import threading

from .teardown import close_impl, is_alive_impl, restart_impl


class PlaywrightManager:
    """Singleton Playwright browser manager — one Chromium instance."""

    _instance = None

    def __new__(cls):
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
        from .launch import enter_impl

        return enter_impl(self)

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        self.close()

    def close(self):
        close_impl(self)

    def _is_alive(self) -> bool:
        return is_alive_impl(self)

    def _restart(self):
        restart_impl(self)

    def _normalize_url(self, url: str) -> str:
        from .url import _normalize_url as _norm

        return _norm(url)

    def _human_like_scroll(self):
        from .scroll import _human_like_scroll as _scroll

        _scroll(self._page)

    def fetch_page_text(self, url: str, timeout: int = 30000,
                        wait_until: str = "domcontentloaded") -> str | None:
        from .fetch_text import fetch_page_text_impl

        return fetch_page_text_impl(self, url, timeout, wait_until)

    def fetch_page_html(self, url: str, timeout: int = 30000) -> str | None:
        from .fetch_html import fetch_page_html_impl

        return fetch_page_html_impl(self, url, timeout)
