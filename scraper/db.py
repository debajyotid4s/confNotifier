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


TERMINAL_STATUSES = ("not_conference", "low_confidence", "extracted", "failed_permanent")


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


def load_domain_strategies() -> dict:
    """Load all cached domain fetch strategies.

    Returns dict[domain, (strategy, loaded_url)].
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT domain, strategy, loaded_url FROM domain_strategies")
        result = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
        cur.close()
        return result
    except Exception as e:
        logger.error("load_domain_strategies error: %s", e)
        return {}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def save_domain_strategy(domain: str, strategy: str, loaded_url: str) -> None:
    """Cache the winning fetch strategy for a domain."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO domain_strategies (domain, strategy, loaded_url) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (domain) DO UPDATE SET "
            "strategy = EXCLUDED.strategy, "
            "loaded_url = EXCLUDED.loaded_url, "
            "updated_at = NOW()",
            (domain, strategy, loaded_url),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("save_domain_strategy error for %s: %s", domain, e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def load_special_path_cache() -> dict:
    """Load cached path patterns for special sources.

    Returns dict[base_url, (year, path_pattern)].
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT base_url, year, path_pattern FROM special_path_cache")
        result = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
        cur.close()
        return result
    except Exception as e:
        logger.error("load_special_path_cache error: %s", e)
        return {}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def save_special_path_cache(base_url: str, year: int, path_pattern: str) -> None:
    """Cache the winning path pattern for a special source."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO special_path_cache (base_url, year, path_pattern) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (base_url) DO UPDATE SET "
            "year = EXCLUDED.year, "
            "path_pattern = EXCLUDED.path_pattern, "
            "updated_at = NOW()",
            (base_url, year, path_pattern),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("save_special_path_cache error for %s: %s", base_url, e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
