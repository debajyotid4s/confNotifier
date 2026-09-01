import logging

from .formatting import _build_conference_message

logger = logging.getLogger(__name__)


def notify(conference: dict) -> bool:
    """Announce a conference on the channel. Returns True when sent."""
    # Late import via package so monkeypatching scraper.notifier.send_plain_message works.
    from scraper.notifier import _record_message as _rec
    from scraper.notifier import send_plain_message as _send

    message_id = _send(_build_conference_message(conference))
    if not message_id:
        return False
    _rec(conference.get("website") or "", message_id, "conference")
    logger.info("Notification sent for: %s (msg_id=%s)", conference.get("title"), message_id)
    return True
