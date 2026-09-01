import logging
import os

import requests

from scraper import db

from .channel import _channel
from .config import SEND_TIMEOUT, TELEGRAM_API

logger = logging.getLogger(__name__)


def _post(method: str, payload: dict, timeout: int = SEND_TIMEOUT):
    """POST to the Telegram Bot API. Returns the parsed body or None."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return None
    try:
        resp = requests.post(TELEGRAM_API.format(token, method), json=payload, timeout=timeout)
    except requests.RequestException as e:
        logger.error("Telegram %s request error: %s", method, e)
        return None
    if resp.status_code == 200:
        try:
            return resp.json()
        except ValueError:
            return {}
    logger.error("Telegram %s failed (%d): %s", method, resp.status_code, resp.text[:300])
    return None


def send_plain_message(text: str, *, parse_mode: str = "HTML",
                       disable_web_page_preview: bool = True) -> int | bool:
    """Post a message to the configured channel. Returns message id or False."""
    channel = _channel()
    if not channel:
        logger.error("TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK not set")
        return False
    payload = {"chat_id": channel, "text": text, "parse_mode": parse_mode}
    if disable_web_page_preview:
        payload["disable_web_page_preview"] = True
    body = _post("sendMessage", payload)
    if body is None:
        return False
    message_id = (body.get("result") or {}).get("message_id")
    return int(message_id) if message_id else True


def delete_message(message_id: int) -> bool:
    """Delete a previously posted message."""
    channel = _channel()
    if not channel or not message_id:
        return False
    body = _post("deleteMessage", {"chat_id": channel, "message_id": int(message_id)},
                 timeout=10)
    if body is not None:
        logger.info("Telegram message %d deleted", message_id)
        return True
    return False


def delete_last_message_for_website(website: str, message_type: str | None = None) -> bool:
    """Delete the most recent post for a website — used to retract a false alert."""
    message_id = db.get_last_telegram_message(website, message_type)
    if not message_id:
        logger.warning("No stored message_id for %s (%s)", website, message_type)
        return False
    return delete_message(message_id)
