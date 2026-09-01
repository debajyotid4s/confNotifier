"""scraper/db/telegram/messages.py — telegram_messages table."""

from scraper.db.connection import _safe, db_cursor, normalize_website


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
