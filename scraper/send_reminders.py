"""
Standalone daily deadline reminder sender.
Runs independently of the main scraper — no Selenium, no crt.sh, no LLM.
Queries upcoming submission deadlines and posts a premium progress-bar
style Telegram message to the channel.
"""

import logging
import os
import sys
import time
from datetime import date

import re

import psycopg2
import requests

_MDV2_SPECIAL = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def _escape_md(text: str) -> str:
    return _MDV2_SPECIAL.sub(r"\\\1", text)

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
    return f"\\[{('█' * filled) + ('░' * empty)}\\]"


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
                   submission_deadline_2, submission_deadline_2_label
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

        for title, website, dl1, label1, dl2, label2 in rows:
            if _within_30_days(dl1):
                entries.append((dl1, website, title))
            if _within_30_days(dl2):
                entries.append((dl2, website, title))

        if not entries:
            logger.info("no upcoming deadlines, skipping")
            return

        entries.sort(key=lambda x: (x[0], x[2]))

        deadline_lines = []
        links = []
        seen_websites = set()

        for dl, website, title in entries:
            days_left = (dl - date.today()).days
            pct = _loaded_pct(days_left)
            bar = _progress_bar(pct)
            emoji = _urgency_emoji(days_left)
            month_day = dl.strftime("%b %d")

            deadline_lines.append(
                f"{emoji} {_escape_md(month_day)} — {_escape_md(title)}\n"
                f"{bar} *{pct}%* Loaded"
            )

            domain = website.replace("https://", "").replace("http://", "").rstrip("/")
            if domain not in seen_websites:
                seen_websites.add(domain)
                links.append(f"• {_escape_md(domain)}")

        deadline_block = "\n\n".join(deadline_lines)
        link_block = "\n".join(links)

        message = (
            "📚 *Upcoming Deadlines*\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"{deadline_block}\n\n"
            "🔗 *Official Links:*\n"
            f"{link_block}\n\n"
            "\\#Bangladesh2026 \\#CallForPapers"
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
                "parse_mode": "MarkdownV2",
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

    send_deadline_reminders()
    logger.info("=== Daily Reminder Run Complete ===")


if __name__ == "__main__":
    main()
