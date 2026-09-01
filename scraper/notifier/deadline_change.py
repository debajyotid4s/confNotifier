import logging

from scraper.utils import escape_html

logger = logging.getLogger(__name__)


def send_deadline_change_notification(title, website, changes) -> None:
    """Announce that a deadline moved.

    `changes` is a list of {"old", "new", "label"}. Entries without an old value
    are first-time discoveries, not changes, and are skipped.
    """
    lines = []
    for change in changes:
        if not change.get("old"):
            logger.warning("deadline_verification: skipping %s — no previous deadline", title)
            continue
        old_str = change["old"].strftime("%b %d")
        new_str = change["new"].strftime("%b %d") if change.get("new") else "Unknown"
        label = change.get("label") or ""
        prefix = f"{escape_html(label)}: " if label else "  "
        lines.append(f"{prefix}<s>{old_str}</s> → <b>{new_str}</b> 📝 <i>Updated</i>")
    if not lines:
        return
    message = (
        f"📢 <b>Deadline Updated</b>\n\n"
        f"<b>{escape_html(title)}</b>\n\n"
        f"{chr(10).join(lines)}\n\n"
        f"🔗 <a href=\"{escape_html(website)}\">{escape_html(website)}</a>"
    )
    from scraper.notifier import _record_message as _rec
    from scraper.notifier import send_plain_message as _send

    message_id = _send(message)
    if message_id:
        _rec(website, message_id, "deadline_change")
        logger.info("deadline_verification: sent change notification for %s (msg_id=%s)",
                    title, message_id)
