import logging
import os
import time

import psycopg2

logger = logging.getLogger(__name__)


def _get_db_connection():
    """Create and return a new database connection with retry logic."""
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
                time.sleep(5)
    raise RuntimeError("Could not connect to database after 3 attempts")


def is_duplicate(conference_data):
    """Check if a conference already exists in the database.

    Matches on website URL (primary) or title + date_start (secondary).

    Args:
        conference_data: Dict with keys 'website', 'title', 'date_start'.

    Returns:
        True if the conference already exists, False otherwise.
    """
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM conferences WHERE website = %s OR (title ILIKE %s AND date_start = %s)",
            (
                conference_data.get("website", ""),
                conference_data.get("title", ""),
                conference_data.get("date_start"),
            ),
        )
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception as e:
        logger.error("Deduplication check error: %s", e)
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as e:
                logger.error("Error closing DB connection: %s", e)
