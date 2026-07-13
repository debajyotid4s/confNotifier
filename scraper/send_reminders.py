"""
Stand-alone daily deadline reminder sender + crt.sh discovery.
Runs independently of the main scraper — no Selenium, no LLM.
Queries upcoming submission deadlines and posts an HTML-formatted
Telegram message to the channel. crt_monitor runs first (once daily).
"""

import logging
import os
import sys
import time
from datetime import date, datetime, timezone

import psycopg2
import requests

from scraper.sources.crt_monitor import run as crt_monitor_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("send_reminders")

MAX_DAYS = 30
BAR_LEN = 20


def _get_db_connection():
    dsn = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            return psycopg2.connect(dsn)
        except psycopg2.Error as e:
            logger.error("DB connection attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError("Could not connect to database after 3 attempts")


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _within_30_days(d) -> bool:
    if d is None:
        return False
    delta = (d - date.today()).days
    return 0 <= delta <= 30


def _loaded_pct(days_left: int) -> int:
    pct = round(100 - (days_left / MAX_DAYS) * 100)
    return max(0, min(100, pct))


def _progress_bar(pct: int) -> str:
    filled = round(pct / 100 * BAR_LEN)
    empty = BAR_LEN - filled
    return f"[{'█' * filled}{'░' * empty}]"


def _urgency_emoji(days_left: int) -> str:
    if days_left <= 7:
        return "🔥"
    if days_left <= 20:
        return "⏳"
    return "✅"


def send_deadline_reminders() -> None:
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT title, website,
                   submission_deadline, submission_deadline_label,
                   submission_deadline_2, submission_deadline_2_label,
                   submission_deadline_previous, submission_deadline_2_previous
            FROM conferences
            WHERE (
                (submission_deadline IS NOT NULL
                 AND submission_deadline >= CURRENT_DATE
                 AND submission_deadline <= CURRENT_DATE + INTERVAL '30 days')
                OR
                (submission_deadline_2 IS NOT NULL
                 AND submission_deadline_2 >= CURRENT_DATE
                 AND submission_deadline_2 <= CURRENT_DATE + INTERVAL '30 days')
            )
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        conn = None

        entries = []

        for title, website, dl1, label1, dl2, label2, dl1_prev, dl2_prev in rows:
            if _within_30_days(dl1):
                is_updated = dl1_prev is not None and dl1_prev != dl1
                entries.append((dl1, website, title, is_updated, dl1_prev if is_updated else None))
            if _within_30_days(dl2):
                is_updated = dl2_prev is not None and dl2_prev != dl2
                entries.append((dl2, website, title, is_updated, dl2_prev if is_updated else None))

        if not entries:
            logger.info("no upcoming deadlines, skipping")
            return

        entries.sort(key=lambda x: (x[0], x[2]))

        deadline_lines = []
        links = []
        seen_websites = set()

        for dl, website, title, is_updated, prev_dl in entries:
            days_left = (dl - date.today()).days
            pct = _loaded_pct(days_left)
            bar = _progress_bar(pct)
            emoji = _urgency_emoji(days_left)
            date_str = dl.strftime("%b %d")
            short_title = _escape_html(title.split(",")[0].split("(")[0].split(":")[0].strip())
            link = f"<a href=\"{_escape_html(website)}\">{_escape_html(short_title)}</a>"

            if is_updated and prev_dl:
                old_str = prev_dl.strftime("%b %d")
                deadline_lines.append(
                    f"{emoji} <s>{old_str}</s> → <b>{date_str}</b> 📝 <i>Updated</i> — {link}\n"
                    f"<code>{bar} {pct}%</code>"
                )
            else:
                deadline_lines.append(
                    f"{emoji} <b>{date_str}</b> — {link}\n"
                    f"<code>{bar} {pct}%</code>"
                )

            domain = website.replace("https://", "").replace("http://", "").rstrip("/")
            if domain not in seen_websites:
                seen_websites.add(domain)
                links.append(f"- {domain}")

        deadline_block = "\n\n".join(deadline_lines)
        link_block = "\n".join(links)

        now_utc = datetime.now(timezone.utc).strftime("%H:%M")

        message = (
            f"<b>📚 UPCOMING DEADLINES</b>\n"
            f"<i>Auto-tracked · updates in real time</i>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"{deadline_block}\n\n"
            f"<blockquote expandable>\n"
            f"🔗 <b>Official Links</b>\n"
            f"{link_block}\n"
            f"</blockquote>\n\n"
            f"#Bangladesh2026 #CallForPapers\n"
            f"<i>Last synced: {now_utc} UTC</i>"
        )

        token = os.environ["TELEGRAM_BOT_TOKEN"]
        channel = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
        if channel.startswith("https://t.me/"):
            channel = "@" + channel.split("https://t.me/")[1]

        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": channel,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("sent reminder for %d deadline entr%s", len(entries), "y" if len(entries) == 1 else "ies")
        else:
            logger.error("Telegram send failed (%d): %s", resp.status_code, resp.text)

    except Exception as e:
        logger.error("send_deadline_reminders error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def main():
    logger.info("=== Daily Reminder Run Started ===")

    for var in ["DATABASE_URL", "TELEGRAM_BOT_TOKEN"]:
        if not os.environ.get(var):
            logger.critical("Missing required env var: %s", var)
            sys.exit(1)
    if not (os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK")):
        logger.critical("Missing TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK")
        sys.exit(1)

    # Run crt.sh discovery once daily before sending reminders
    # Decoupled from the 5×/day scraper pipeline — certificates don't churn within hours
    try:
        new_candidates = crt_monitor_run()
        if new_candidates:
            logger.info("crt_monitor: discovered %d new candidate(s)", len(new_candidates))
    except Exception as e:
        logger.error("crt_monitor failed: %s", e)

    send_deadline_reminders()
    logger.info("=== Daily Reminder Run Complete ===")


if __name__ == "__main__":
    main()
