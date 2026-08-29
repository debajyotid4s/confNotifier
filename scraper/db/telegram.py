"""scraper/db/telegram.py — Telegram message bookkeeping + notify flags."""

import logging
import time
from datetime import datetime, timezone

from scraper.db.connection import _safe, db_cursor, normalize_website

logger = logging.getLogger(__name__)


@_safe("mark_notified", default=False)
def mark_notified(conf_id: int) -> bool:
    """Flag a conference as announced so it is never posted twice."""
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE id = %s", (conf_id,))
    return True


def mark_notified_with_retry(conf_id: int, max_attempts: int = 3) -> bool:
    """Flag a conference as announced, retrying so a blip cannot cause a repost."""
    for attempt in range(max_attempts):
        if mark_notified(conf_id):
            return True
        logger.error("mark_notified attempt %d/%d failed for id=%s", attempt + 1, max_attempts, conf_id)
        time.sleep(2)
    logger.critical("mark_notified FAILED all %d attempts for id=%s — duplicate notification risk", max_attempts, conf_id)
    return False


@_safe("mark_past_conferences_notified", default=0)
def mark_past_conferences_notified() -> int:
    """Suppress announcements for conferences that already started."""
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE is_notified = FALSE AND date_start < CURRENT_DATE")
        return cur.rowcount


@_safe("mark_verification_done")
def mark_verification_done() -> None:
    """Stamp the deadline-verification run so the interval guard can throttle it."""
    now = datetime.now(timezone.utc)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO daily_tasks (task_name, last_run_date) VALUES ('deadline_verification', %s) "
            "ON CONFLICT (task_name) DO UPDATE SET last_run_date = EXCLUDED.last_run_date",
            (now,),
        )


@_safe("get_task_last_run", default=None)
def get_task_last_run(task_name: str):
    """Timestamp of a task's last run, or None if it never ran."""
    with db_cursor() as cur:
        cur.execute("SELECT last_run_date FROM daily_tasks WHERE task_name = %s", (task_name,))
        row = cur.fetchone()
    return row[0] if row else None


# ── Telegram message bookkeeping ─────────────────────────────────────────────

@_safe("ensure_telegram_messages_table")
def ensure_telegram_messages_table() -> None:
    """Create telegram_messages if a fresh database has not been migrated yet."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_messages (
                id SERIAL PRIMARY KEY,
                website TEXT NOT NULL,
                message_id BIGINT NOT NULL,
                message_type TEXT NOT NULL,
                chat_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(website, message_id)
            )
            """
        )


@_safe("save_telegram_message")
def save_telegram_message(website: str, message_id: int, message_type: str, chat_id: str | None = None) -> None:
    """Store a posted message id so it can be deleted later."""
    if not website or not message_id:
        return
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO telegram_messages (website, message_id, message_type, chat_id) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (website, message_id) DO NOTHING",
            (normalize_website(website), int(message_id), message_type, chat_id),
        )


@_safe("get_last_telegram_message", default=None)
def get_last_telegram_message(website: str, message_type: str | None = None) -> int | None:
    """Most recent message id posted for a website, optionally by type."""
    with db_cursor() as cur:
        if message_type:
            cur.execute(
                "SELECT message_id FROM telegram_messages "
                "WHERE website = %s AND message_type = %s ORDER BY created_at DESC LIMIT 1",
                (normalize_website(website), message_type),
            )
        else:
            cur.execute("SELECT message_id FROM telegram_messages WHERE website = %s ORDER BY created_at DESC LIMIT 1", (normalize_website(website),))
        row = cur.fetchone()
    return int(row[0]) if row else None
