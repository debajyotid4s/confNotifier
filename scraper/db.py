import logging
import os
import time

import psycopg2

logger = logging.getLogger(__name__)


def get_connection():
    """Create and return a new database connection with retry logic.

    Retries 3 times with 5s delay between attempts.
    Raises RuntimeError if all attempts fail.
    """
    dsn = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            return psycopg2.connect(dsn)
        except psycopg2.Error as e:
            logger.error("DB connection attempt %d/3 failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(5)
    raise RuntimeError("Could not connect to database after 3 attempts")


TERMINAL_STATUSES = ("not_conference", "low_confidence", "extracted", "failed")


def save_seen_link(url, source="unknown", status="pending"):
    """Insert or update a URL in seen_links with its processing status.

    Status lifecycle (DFS — once terminal, never re-checked):
        pending        → newly discovered, awaiting extraction
        not_conference → LLM determined not a conference (DONE)
        low_confidence → below 0.75 threshold (DONE)
        extracted      → conference saved and notified (DONE for this edition)
        failed         → extraction failed, dead URL (DONE, skip forever)

    Once a URL reaches a terminal status, it is never overwritten back to pending.
    This prevents sources from rediscovering dead URLs and wasting Selenium time.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO seen_links (url, source, status) VALUES (%s, %s, %s) "
            "ON CONFLICT (url) DO UPDATE SET "
            "source = EXCLUDED.source, "
            "status = EXCLUDED.status, "
            "last_seen = NOW() "
            "WHERE seen_links.status NOT IN %s",
            (url, source, status, TERMINAL_STATUSES),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("save_seen_link error for %s: %s", url, e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
