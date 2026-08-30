"""Public entry points the scraper calls — simple, never breaks scraper."""

import logging

from data_collection import db

logger = logging.getLogger(__name__)


def record_confirmed(url: str, *, source: str = "scraper_daily", anchor_text: str = None, page_title: str = None) -> None:
    """Conference confirmed by regex/Gemini -> label 1."""
    try:
        db.insert(url=url, raw_url=url, label=1, source=source)
    except Exception as e:
        logger.error("collector.record_confirmed failed for %s: %s", url, e)


def record_unconfirmed(url: str, *, reason: str = "regex_rejected", anchor_text: str = None, page_title: str = None) -> None:
    """Other link discovered by scraper -> label 0. reason is kept for logs only."""
    try:
        db.insert(url=url, raw_url=url, label=0, source="scraper_daily")
    except Exception as e:
        logger.error("collector.record_unconfirmed failed for %s: %s", url, e)
