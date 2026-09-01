"""scraper/reminders/runner.py — digest runner + CLI."""

import logging
import os
import sys

from scraper.notifier import send_plain_message
from scraper.reminders.queries import _fetch_entries
from scraper.reminders.render import _render
from scraper.sources.crt_monitor import run as crt_monitor_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("send_reminders")


def send_deadline_reminders() -> None:
    """Post the upcoming-deadline digest to the channel."""
    try:
        entries = _fetch_entries()
    except Exception as e:
        logger.error("send_deadline_reminders: query failed: %s", e)
        return
    if not entries:
        logger.info("no upcoming deadlines, skipping digest")
        return
    if send_plain_message(_render(entries)):
        logger.info("sent reminder for %d deadline entr%s", len(entries), "y" if len(entries) == 1 else "ies")


def main():
    logger.info("=== Daily Reminder Run Started ===")
    for var in ("DATABASE_URL", "TELEGRAM_BOT_TOKEN"):
        if not os.environ.get(var):
            logger.critical("Missing required env var: %s", var)
            sys.exit(1)
    if not (os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK")):
        logger.critical("Missing TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK")
        sys.exit(1)
    try:
        discovered = crt_monitor_run()
        if discovered:
            logger.info("crt_monitor: discovered %d new candidate(s)", len(discovered))
    except Exception as e:
        logger.error("crt_monitor failed: %s", e)
    send_deadline_reminders()
    logger.info("=== Daily Reminder Run Complete ===")
