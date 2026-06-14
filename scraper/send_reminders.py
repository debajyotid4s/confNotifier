"""
Standalone daily deadline reminder sender.
Runs independently of the main scraper — no Selenium, no crt.sh, no LLM.
Checks the daily_tasks table to ensure it sends at most once per UTC day,
then queries upcoming submission deadlines and posts a grouped Telegram
message to the channel.
"""

import logging
import os
import sys
import time
from datetime import date

import psycopg2
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("send_reminders")

TASK_NAME = "deadline_reminders"


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


def _ensure_table() -> None:
    """Create daily_tasks table if it doesn't exist (idempotent)."""
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_tasks (
                task_name TEXT PRIMARY KEY,
                last_run_date DATE
            )
            """
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("_ensure_table error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _was_task_run_today() -> bool:
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT last_run_date FROM daily_tasks WHERE task_name = %s",
            (TASK_NAME,)
        )
        row = cur.fetchone()
        cur.close()
        if row is None:
            return False
        return row[0] == date.today()
    except Exception as e:
        logger.error("_was_task_run_today error: %s", e)
        return True  # fail safe: skip rather than spam
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _mark_task_run_today() -> None:
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO daily_tasks (task_name, last_run_date)
            VALUES (%s, %s)
            ON CONFLICT (task_name) DO UPDATE SET last_run_date = %s
            """,
            (TASK_NAME, date.today(), date.today())
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("_mark_task_run_today error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _within_30_days(d) -> bool:
    if d is None:
        return False
    delta = (d - date.today()).days
    return 0 <= delta <= 30


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
        logging.info("DEBUG: query returned %d rows", len(rows))
        for row in rows:
            logging.info("DEBUG: row=%s", row)
        cur.close()
        conn.close()
        conn = None

        today = date.today()
        logging.info("DEBUG: today=%s", today)
        entries = []

        for title, website, dl1, label1, dl2, label2 in rows:
            logging.info("DEBUG: title=%s, dl1=%s (%s), dl2=%s (%s), within30_dl1=%s, within30_dl2=%s",
                         title, dl1, type(dl1).__name__, dl2, type(dl2).__name__,
                         _within_30_days(dl1), _within_30_days(dl2))
            if _within_30_days(dl1):
                days_left = (dl1 - today).days
                label = label1 or "Submission Deadline"
                entries.append((dl1, (
                    f"📌 {title}\n"
                    f"   {label}: {dl1.strftime('%B %d, %Y')} (in {days_left} day{'s' if days_left != 1 else ''})\n"
                    f"   🔗 {website}"
                )))
            if _within_30_days(dl2):
                days_left = (dl2 - today).days
                label = label2 or "Deadline"
                entries.append((dl2, (
                    f"📌 {title}\n"
                    f"   {label}: {dl2.strftime('%B %d, %Y')} (in {days_left} day{'s' if days_left != 1 else ''})\n"
                    f"   🔗 {website}"
                )))
        logging.info("DEBUG: %d entries after filtering", len(entries))

        if not entries:
            logger.info("no upcoming deadlines, skipping")
            return

        entries.sort(key=lambda x: x[0])
        lines = [line for _, line in entries]
        body = "\n\n".join(lines)

        message = (
            "📚 *Paper Submission Deadline Reminder*\n\n"
            "My Dear Research Enthusiasts,\n\n"
            "Here are the upcoming paper submission deadlines:\n\n"
            f"{body}\n\n"
            "Don't miss out\\! Plan your submissions accordingly\\.\n\n"
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

    _ensure_table()

    if _was_task_run_today():
        logger.info("already sent today, skipping")
        return

    send_deadline_reminders()
    _mark_task_run_today()
    logger.info("=== Daily Reminder Run Complete ===")


if __name__ == "__main__":
    main()
