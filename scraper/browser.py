import logging
import random
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import WebDriverException

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def create_driver():
    """Create and return a configured Selenium Chrome driver with anti-bot measures."""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    user_agent = random.choice(USER_AGENTS)
    opts.add_argument(f"--user-agent={user_agent}")
    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd(
        "Network.setUserAgentOverride", {"userAgent": user_agent}
    )
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    driver.set_page_load_timeout(20)
    driver.set_script_timeout(10)
    return driver


def human_delay(min_sec=1.5, max_sec=4.0):
    """Sleep for a random interval to mimic human timing."""
    time.sleep(random.uniform(min_sec, max_sec))


def slow_scroll(driver, min_steps=4, max_steps=8):
    """Scroll the page slowly in random steps."""
    height = driver.execute_script("return document.body.scrollHeight")
    steps = random.randint(min_steps, max_steps)
    for i in range(1, steps + 1):
        target = height * (i / steps) + random.randint(-50, 50)
        target = max(0, min(target, height))
        driver.execute_script(f"window.scrollTo(0, {target})")
        time.sleep(random.uniform(0.3, 0.8))


def random_mouse_movement(driver, moves=3):
    """Perform random micro mouse movements using ActionChains."""
    actions = ActionChains(driver)
    for _ in range(moves):
        x_offset = random.randint(-100, 100)
        y_offset = random.randint(-100, 100)
        try:
            actions.move_by_offset(x_offset, y_offset)
            actions.pause(random.uniform(0.1, 0.4))
        except Exception:
            pass
    try:
        actions.perform()
    except Exception:
        pass


def load_page(driver, url, retries=1):
    """Load a URL in the driver with retry logic and human-like behavior.

    Args:
        driver: Selenium WebDriver instance.
        url: The URL to load.
        retries: Number of retry attempts on failure.

    Returns:
        True if page loaded successfully, False otherwise.
    """
    for attempt in range(retries + 1):
        try:
            driver.get(url)
            human_delay()
            slow_scroll(driver)
            random_mouse_movement(driver)
            return True
        except WebDriverException as e:
            logger.warning(
                "Failed to load %s (attempt %d/%d): %s",
                url, attempt + 1, retries + 1, e,
            )
            if attempt < retries:
                time.sleep(5)
    return False


class BrowserManager:
    """Context manager for safe Selenium WebDriver lifecycle."""

    def __init__(self):
        self.driver = None

    def __enter__(self):
        self.driver = create_driver()
        return self.driver

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error("Error quitting driver: %s", e)
