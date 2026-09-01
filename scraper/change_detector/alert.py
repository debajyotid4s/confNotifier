import logging
from datetime import datetime, timezone

from scraper import db
from scraper.utils import escape_html

from .constants import ALERT_INTERVAL_HOURS
from .state import _as_utc

logger = logging.getLogger(__name__)


def _alert_if_due(domain: str, baseline: int, verdict: dict) -> None:
    """Send a Telegram alert for a confirmed structure change, at most daily."""
    # Late import so patching scraper.notifier.send_plain_message is respected.
    from scraper.notifier import send_plain_message

    try:
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "SELECT last_alerted_at FROM domain_stats WHERE domain = %s", (domain,)
            )
            row = cur.fetchone()
            if row and row[0]:
                hours = (datetime.now(timezone.utc) - _as_utc(row[0])).total_seconds() / 3600
                if hours < ALERT_INTERVAL_HOURS:
                    return
            new_links = verdict.get("new_links") or []
            lines = [
                "⚠️ <b>Homepage change detected</b>",
                "",
                f"<b>{escape_html(domain)}</b> — previously ~{baseline} conference "
                f"link(s) on the homepage, now 0.",
                f"Verdict: <b>{escape_html(verdict.get('verdict', ''))}</b>",
            ]
            if verdict.get("reason"):
                lines.append(f"Reason: {escape_html(verdict['reason'])}")
            if new_links:
                lines += ["", "New conference links found:"]
                lines += [f"  • {escape_html(u)}" for u in new_links[:5]]
            if send_plain_message("\n".join(lines)):
                cur.execute(
                    "UPDATE domain_stats SET last_alerted_at = NOW() WHERE domain = %s",
                    (domain,),
                )
                logger.info("change_detector: alerted for %s", domain)
    except Exception as e:
        logger.error("change_detector: alert error for %s: %s", domain, e)
