import logging

logger = logging.getLogger(__name__)


def _clear_state(mgr) -> None:
    mgr._page = None
    mgr._context = None
    mgr._browser = None
    mgr._pw = None


def _close_resources(mgr) -> None:
    try:
        if mgr._page and not mgr._page.is_closed():
            mgr._page.close()
    except Exception:
        pass
    try:
        if mgr._context:
            mgr._context.close()
    except Exception:
        pass
    try:
        if mgr._browser:
            mgr._browser.close()
    except Exception:
        pass
    try:
        if mgr._pw:
            mgr._pw.stop()
    except Exception:
        pass


def close_impl(mgr) -> None:
    """Gracefully shut down browser and Playwright."""
    _close_resources(mgr)
    _clear_state(mgr)
    mgr._initialized = False
    logger.info("PlaywrightManager: browser closed")


def is_alive_impl(mgr) -> bool:
    """Check if the browser process is still responsive."""
    try:
        mgr._page.evaluate("1 + 1")
        return True
    except Exception:
        return False


def restart_impl(mgr) -> None:
    """Close and relaunch the browser. Called when crash is detected."""
    logger.warning("PlaywrightManager: restarting browser after crash")
    _close_resources(mgr)
    _clear_state(mgr)
    mgr.__enter__()
