import os

from scraper.utils import resolve_channel


def _channel() -> str:
    """Configured channel as an @handle or numeric chat id."""
    return resolve_channel(
        os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
    )
