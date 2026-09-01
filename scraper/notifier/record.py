import logging

from scraper import db

from .channel import _channel

logger = logging.getLogger(__name__)


def _record_message(website: str, message_id, message_type: str) -> None:
    """Store a posted message id so it can be retracted later."""
    if not isinstance(message_id, int):
        return
    try:
        db.ensure_telegram_messages_table()
        db.save_telegram_message(website, message_id, message_type, _channel())
    except Exception as e:
        logger.debug("could not record telegram message for %s: %s", website, e)
