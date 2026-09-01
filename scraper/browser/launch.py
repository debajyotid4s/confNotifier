import logging
import random

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .constants import USER_AGENTS

logger = logging.getLogger(__name__)


def enter_impl(mgr):
    if mgr._page is not None:
        return mgr
    try:
        mgr._pw = sync_playwright().start()
        mgr._browser = mgr._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        user_agent = random.choice(USER_AGENTS)
        mgr._context = mgr._browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        Stealth().apply_stealth_sync(mgr._context)
        mgr._page = mgr._context.new_page()
        logger.info("PlaywrightManager: Chromium launched with stealth")
        return mgr
    except Exception as e:
        logger.critical("PlaywrightManager: failed to launch browser: %s", e)
        mgr.close()
        raise
