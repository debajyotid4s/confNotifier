"""Stand-alone deadline verification entry point.

Runs verify_deadlines with a fresh PlaywrightManager.
Used by the separate GHA workflow at 15:00 UTC (9pm Bangladesh).
"""
import logging
import os
import sys

from scraper.browser import PlaywrightManager
from scraper.db import get_connection
from scraper.verifier import verify_deadlines

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    for var in ["DATABASE_URL", "GOOGLE_AI_KEY", "TELEGRAM_BOT_TOKEN"]:
        if var not in os.environ or not os.environ[var].strip():
            print(f"ERROR: Missing or empty environment variable: {var}")
            sys.exit(1)

    try:
        conn = get_connection()
        conn.close()
        logger.info("Connected to PostgreSQL")
    except Exception as e:
        logger.critical("Cannot connect to PostgreSQL: %s", e)
        sys.exit(1)

    try:
        with PlaywrightManager() as playwright:
            verify_deadlines(playwright)
    except Exception as e:
        logger.critical(
            "Browser failed to launch — skipping deadline verification: %s", e
        )


if __name__ == "__main__":
    main()
