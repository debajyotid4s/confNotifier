import logging
import os
import sys
import time
from datetime import datetime

import psycopg2

from sources import crt_monitor, homepage_links, special
from extractor import extract
from deduplicator import is_duplicate
from notifier import notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
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


def _save_conference(conn, data):
    """Insert a conference record into the database.

    Args:
        conn: Active database connection.
        data: Dict with conference fields.

    Returns:
        The new conference id, or None on failure.
    """
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO conferences "
            "(title, date_start, date_end, city, country, website, organizer, category, confidence, raw_source) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (
                data.get("title", ""),
                data.get("date_start"),
                data.get("date_end"),
                data.get("city"),
                data.get("country", "Bangladesh"),
                data.get("website", ""),
                data.get("organizer"),
                data.get("category"),
                data.get("confidence", 0.0),
                data.get("raw_source", ""),
            ),
        )
        conn.commit()
        conference_id = cur.fetchone()[0]
        cur.close()
        return conference_id
    except psycopg2.Error as e:
        conn.rollback()
        logger.error("Error saving conference: %s", e)
        return None


def _save_seen_link(conn, url):
    """Mark a URL as seen so it won't be reprocessed."""
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO seen_links (url, source) VALUES (%s, 'extractor') "
            "ON CONFLICT (url) DO UPDATE SET last_seen = NOW()",
            (url,),
        )
        conn.commit()
        cur.close()
    except psycopg2.Error as e:
        conn.rollback()
        logger.error("Error saving seen link %s: %s", url, e)


def run():
    """Main orchestrator: discover, extract, deduplicate, notify.

    Runs all three source detectors, combines candidates, and processes
    each through extraction, deduplication, saving, and notification.
    """
    for var in ["DATABASE_URL", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID"]:
        if var not in os.environ:
            print(f"ERROR: Missing required environment variable: {var}")
            sys.exit(1)
    logger.info("=== BD Conference Bot Run Started ===")
    conn = None
    try:
        conn = _get_db_connection()
        logger.info("Connected to PostgreSQL")

        # Phase 1
        try:
            crt_candidates = crt_monitor.run()
            logger.info("crt_monitor returned %d candidates", len(crt_candidates))
        except Exception as e:
            logger.error("crt_monitor failed: %s", e)
            crt_candidates = []

        # Phase 2
        try:
            homepage_candidates = homepage_links.run()
            logger.info("homepage_links returned %d candidates", len(homepage_candidates))
        except Exception as e:
            logger.error("homepage_links failed: %s", e)
            homepage_candidates = []

        # Phase 3
        try:
            special_candidates = special.run()
            logger.info("special returned %d candidates", len(special_candidates))
        except Exception as e:
            logger.error("special failed: %s", e)
            special_candidates = []

        all_candidates = list(
            set(crt_candidates + homepage_candidates + special_candidates)
        )
        logger.info("Phase 4: Processing %d unique candidates", len(all_candidates))

        found = len(all_candidates)
        new_count = 0
        skipped = 0
        failed = 0

        for url in all_candidates:
            logger.info("Extracting data from: %s", url)
            result = extract(url)
            if result is None:
                logger.warning("Extraction failed for: %s", url)
                failed += 1
                continue

            if not result.get("is_conference", False):
                logger.info("Not a conference, skipping: %s", url)
                _save_seen_link(conn, url)
                skipped += 1
                continue

            try:
                is_dup = is_duplicate(result)
            except Exception as e:
                logger.error("Dedup DB error for %s, skipping to be safe: %s", url, e)
                continue
            if is_dup:
                logger.info("Duplicate conference, skipping: %s", url)
                skipped += 1
                continue

            result["raw_source"] = url
            conf_id = _save_conference(conn, result)
            if conf_id is None:
                failed += 1
                continue

            logger.info(
                "New conference saved (id=%s): %s", conf_id, result.get("title"),
            )

            if notify(result):
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE id = %s",
                        (conf_id,),
                    )
                    conn.commit()
                    cur.close()
                except psycopg2.Error as e:
                    conn.rollback()
                    logger.error("Error updating notification status: %s", e)

            new_count += 1

        logger.info(
            "=== Run complete: %d found, %d new, %d skipped, %d failed ===",
            found, new_count, skipped, failed,
        )

    except Exception as e:
        logger.error("Fatal error in main run: %s", e)
        sys.exit(1)
    finally:
        if conn is not None:
            try:
                conn.close()
                logger.info("Database connection closed")
            except Exception as e:
                logger.error("Error closing DB connection: %s", e)


if __name__ == "__main__":
    run()
