"""Daily job: certificate-transparency discovery, then the deadline digest.

Runs without a browser or LLM, so it is cheap enough to schedule separately from
the main scraper. Posts one Telegram message listing every submission deadline in
the next 30 days, with a progress bar showing how much of the window has elapsed
and a strikethrough when the deadline was extended.
"""

import logging
import os
import sys
from datetime import date, datetime, timezone

from scraper import db
from scraper.notifier import send_plain_message
from scraper.schema import SUBMISSION_TYPES, deadline_range_checks
from scraper.sources.crt_monitor import run as crt_monitor_run
from scraper.utils import escape_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("send_reminders")

WINDOW_DAYS = 30
BAR_LEN = 20

URGENT_DAYS = 7
SOON_DAYS = 20


def _urgency_emoji(days_left: int) -> str:
    if days_left <= URGENT_DAYS:
        return "🔥"
    if days_left <= SOON_DAYS:
        return "⏳"
    return "✅"


def _elapsed_pct(days_left: int) -> int:
    """How much of the 30-day window has passed, clamped to 0-100."""
    return max(0, min(100, round(100 - (days_left / WINDOW_DAYS) * 100)))


def _progress_bar(pct: int) -> str:
    filled = round(pct / 100 * BAR_LEN)
    return f"[{'█' * filled}{'░' * (BAR_LEN - filled)}]"


def _within_window(value) -> bool:
    return value is not None and 0 <= (value - date.today()).days <= WINDOW_DAYS


def _fetch_entries() -> list[tuple]:
    """Every upcoming deadline as (deadline, website, title, previous_deadline).

    Only the named deadline columns are read: migration_011 backfilled the legacy
    `submission_deadline*` pair into them, and nothing writes legacy any more.
    """
    columns = []
    for typ in SUBMISSION_TYPES:
        columns += [f"{typ}_deadline", f"{typ}_deadline_previous"]
    window = " OR ".join(deadline_range_checks(WINDOW_DAYS))

    with db.db_cursor() as cur:
        cur.execute(f"""
            SELECT title, website, {", ".join(columns)}
            FROM conferences
            WHERE {window}
        """)
        rows = cur.fetchall()

    entries = []
    for row in rows:
        title, website = row[0], row[1]
        for i, _typ in enumerate(SUBMISSION_TYPES):
            deadline = row[2 + i * 2]
            previous = row[2 + i * 2 + 1]
            if not _within_window(deadline):
                continue
            changed = previous is not None and previous != deadline
            entries.append((deadline, website, title, previous if changed else None))
    return entries


def _render(entries: list[tuple]) -> str:
    """Build the digest message."""
    entries.sort(key=lambda e: (e[0], e[2]))

    blocks, links, seen_domains = [], [], set()
    for deadline, website, title, previous in entries:
        days_left = (deadline - date.today()).days
        pct = _elapsed_pct(days_left)
        short_title = escape_html(title.split(",")[0].split("(")[0].split(":")[0].strip())
        link = f'<a href="{escape_html(website)}">{short_title}</a>'
        date_str = deadline.strftime("%b %d")

        if previous:
            head = (f"{_urgency_emoji(days_left)} <s>{previous.strftime('%b %d')}</s> → "
                    f"<b>{date_str}</b> 📝 <i>Updated</i> — {link}")
        else:
            head = f"{_urgency_emoji(days_left)} <b>{date_str}</b> — {link}"
        blocks.append(f"{head}\n<code>{_progress_bar(pct)} {pct}%</code>")

        domain = (website or "").replace("https://", "").replace("http://", "").rstrip("/")
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            links.append(f"- {domain}")

    deadline_block = "\n\n".join(blocks)
    link_block = "\n".join(links)
    synced_at = datetime.now(timezone.utc).strftime("%H:%M")

    return (
        f"<b>📚 UPCOMING DEADLINES</b>\n"
        f"<i>Auto-tracked · updates in real time</i>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"{deadline_block}\n\n"
        f"<blockquote expandable>\n"
        f"🔗 <b>Official Links</b>\n"
        f"{link_block}\n"
        f"</blockquote>\n\n"
        f"#Bangladesh{datetime.now().year} #CallForPapers\n"
        f"<i>Last synced: {synced_at} UTC</i>"
    )


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
        logger.info("sent reminder for %d deadline entr%s",
                    len(entries), "y" if len(entries) == 1 else "ies")


def main():
    logger.info("=== Daily Reminder Run Started ===")

    for var in ("DATABASE_URL", "TELEGRAM_BOT_TOKEN"):
        if not os.environ.get(var):
            logger.critical("Missing required env var: %s", var)
            sys.exit(1)
    if not (os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK")):
        logger.critical("Missing TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK")
        sys.exit(1)

    # Certificate transparency runs once daily: certificates do not churn hourly,
    # and crt.sh is slow enough that it does not belong in the 5x/day pipeline.
    try:
        discovered = crt_monitor_run()
        if discovered:
            logger.info("crt_monitor: discovered %d new candidate(s)", len(discovered))
    except Exception as e:
        logger.error("crt_monitor failed: %s", e)

    send_deadline_reminders()
    logger.info("=== Daily Reminder Run Complete ===")


if __name__ == "__main__":
    main()
