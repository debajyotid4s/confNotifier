"""
DB per-operation connections — same pattern as scraper/db.py (Neon idle kills).
No long-lived pool.
"""
import os
import time
import logging
import psycopg2

logger = logging.getLogger(__name__)


def get_conn():
    dsn = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            return psycopg2.connect(dsn)
        except psycopg2.Error as e:
            logger.error("DB connect attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)
    raise RuntimeError("DB unavailable after 3 attempts")
