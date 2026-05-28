import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CHANNEL_LINK = "https://t.me/BDConferences"


def _get_db_connection():
    """Create and return a database connection with retry logic."""
    dsn = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            conn = psycopg2.connect(dsn)
            return conn
        except psycopg2.Error as e:
            logger.error(
                "DB connection attempt %d/3 failed: %s", attempt + 1, e,
            )
            if attempt < 2:
                import time
                time.sleep(5)
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message with channel link."""
    await update.message.reply_text(
        f"Welcome to BD Conference Bot \U0001F1E7\U0001F1E9\n\n"
        f"I notify you about newly announced international\n"
        f"conferences in Bangladesh \u2014 automatically, the moment\n"
        f"they go live.\n\n"
        f"\U0001F449 Join our channel: {CHANNEL_LINK}\n"
        f"Use /list to see upcoming conferences."
    )


async def list_conferences(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Query upcoming conferences and send a formatted list."""
    conn = _get_db_connection()
    if conn is None:
        await update.message.reply_text(
            "Sorry, I could not connect to the database right now."
        )
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT title, date_start, city, website FROM conferences "
            "WHERE date_start >= CURRENT_DATE "
            "ORDER BY date_start ASC LIMIT 10"
        )
        rows = cur.fetchall()
        cur.close()
    except psycopg2.Error as e:
        logger.error("Database query error: %s", e)
        await update.message.reply_text(
            "Sorry, an error occurred while fetching conferences."
        )
        return
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not rows:
        await update.message.reply_text(
            "No upcoming conferences found at the moment."
        )
        return

    lines = []
    for title, date_start, city, website in rows:
        date_str = date_start.strftime("%b %d, %Y") if date_start else "TBA"
        city_str = city or "TBA"
        url_str = website or "TBA"
        lines.append(
            f"\U0001F4CC {title} | \U0001F4C5 {date_str} | "
            f"\U0001F4CD {city_str} | \U0001F517 {url_str}"
        )

    await update.message.reply_text(
        "Upcoming International Conferences in Bangladesh:\n\n"
        + "\n\n".join(lines)
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the channel join link."""
    await update.message.reply_text(
        f"To receive instant conference notifications:\n\n"
        f"1. Tap the link below\n"
        f"2. Join the channel\n"
        f"3. You\u2019ll get notified automatically!\n\n"
        f"{CHANNEL_LINK}"
    )


def main():
    """Start the bot in webhook mode for Koyeb deployment."""
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_conferences))
    app.add_handler(CommandHandler("subscribe", subscribe))

    port = int(os.environ.get("PORT", 8080))
    webhook_url = os.environ.get(
        "WEBHOOK_URL", f"https://localhost:{port}/webhook"
    )

    logger.info("Starting webhook on port %s with URL %s", port, webhook_url)
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=f"{webhook_url}/{token}",
    )


if __name__ == "__main__":
    main()
