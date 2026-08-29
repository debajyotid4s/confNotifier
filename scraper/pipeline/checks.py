"""scraper/pipeline/checks.py — startup environment & dependency checks."""

import logging
import os
import sys

import requests

from scraper import db

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = ["DATABASE_URL", "GOOGLE_AI_KEY", "TELEGRAM_BOT_TOKEN"]
CHANNEL_ENV_VARS = ["TELEGRAM_CHANNEL_ID", "TELEGRAM_CHANNEL_LINK"]


def check_environment() -> None:
    """Fail fast on missing configuration. Only names and lengths are logged."""
    missing = [var for var in REQUIRED_ENV_VARS if not (os.environ.get(var) or "").strip()]
    for var in REQUIRED_ENV_VARS:
        value = os.environ.get(var)
        if value and value.strip():
            logger.info("%s: OK (%d chars)", var, len(value))
    if missing:
        print(f"ERROR: Missing or empty environment variable(s): {', '.join(missing)}")
        print("  Set it in GitHub repo -> Settings -> Secrets -> Actions")
        sys.exit(1)
    if not any((os.environ.get(var) or "").strip() for var in CHANNEL_ENV_VARS):
        print(f"ERROR: Missing environment variable: {' or '.join(CHANNEL_ENV_VARS)}")
        sys.exit(1)


def verify_dependencies() -> None:
    """Confirm the database and Telegram channel are reachable before starting."""
    try:
        db.get_connection().close()
        logger.info("Connected to PostgreSQL")
    except Exception as e:
        logger.critical("Cannot connect to PostgreSQL: %s", e)
        sys.exit(1)

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    channel = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getChat", params={"chat_id": channel}, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram channel access verified")
        else:
            logger.warning("Telegram channel check failed (%d)", resp.status_code)
    except Exception as e:
        logger.warning("Telegram channel check error: %s", e)
