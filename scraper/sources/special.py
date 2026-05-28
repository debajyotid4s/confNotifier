import json
import logging
import os
import time
from datetime import datetime

import psycopg2
import requests

logger = logging.getLogger(__name__)


def _load_sources(path="config/special_sources.json"):
    """Load special source base URLs from the JSON config file."""
    with open(path) as f:
        return json.load(f)


def _probe_url(url, timeout=30):
    """Probe a URL and return True if it returns HTTP 200 with content > 500 chars.

    Args:
        url: The URL to probe.
        timeout: Request timeout in seconds.

    Returns:
        True if the page exists and has substantial content.
    """
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        if resp.status_code == 200 and len(resp.text) > 500:
            return True
    except requests.RequestException as e:
        logger.debug("Probe failed for %s: %s", url, e)
    return False


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


def run():
    """Probe special conference sources for newly announced editions.

    For each source base URL, probes paths with current year and next year.
    Saves newly seen URLs to the database.

    Returns a list of newly discovered candidate URLs.
    """
    sources = _load_sources()
    year = datetime.now().year
    years_to_check = [str(year), str(year + 1)]
    candidates = []
    conn = None
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT url FROM seen_links WHERE source = 'special'")
        known = {row[0] for row in cur.fetchall()}

        for base in sources:
            base = base.rstrip("/")
            for y in years_to_check:
                url = f"{base}/{y}/"
                if url in known:
                    continue
                if not _probe_url(url):
                    continue
                candidates.append(url)
                known.add(url)
                try:
                    cur.execute(
                        "INSERT INTO seen_links (url, source) VALUES (%s, 'special') "
                        "ON CONFLICT (url) DO UPDATE SET last_seen = NOW()",
                        (url,),
                    )
                    conn.commit()
                except psycopg2.Error as e:
                    conn.rollback()
                    logger.error("DB error saving special URL %s: %s", url, e)

        cur.close()
    except Exception as e:
        logger.error("special.run error: %s", e)
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as e:
                logger.error("Error closing DB connection: %s", e)

    logger.info("special: found %d new special source URLs", len(candidates))
    return candidates
