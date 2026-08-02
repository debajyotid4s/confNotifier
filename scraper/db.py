import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import psycopg2

from scraper.schema import DEADLINE_TYPES

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


# ── URL normalization for consistent dedup ──


def normalize_website(url: str) -> str:
    """Normalize a conference website URL for consistent dedup comparison.

    Strips trailing slash, lowercases hostname, strips www. prefix,
    forces https scheme. Returns empty string for empty/None input.
    """
    if not url:
        return url
    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    if not parsed.hostname:
        return url
    hostname = parsed.hostname.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    path = parsed.path.rstrip("/")
    return urlunparse(("https", hostname, path, parsed.params, parsed.query, parsed.fragment))


# ── Conference persistence ──


def _deadline_columns(conf: dict) -> tuple[list[str], list]:
    """Build column names and values for the 4 named deadline types from extraction result.

    Each deadline type has 2 columns: {type}_deadline (DATE) and {type}_deadline_label (TEXT).
    The _previous columns are omitted here — they are only set during verification.
    Returns (column_names_list, values_list) for use in INSERT.
    """
    cols = []
    vals = []
    for typ in DEADLINE_TYPES:
        cols.append(f"{typ}_deadline")
        cols.append(f"{typ}_deadline_label")
        vals.append(conf.get(f"{typ}_deadline"))
        vals.append(conf.get(f"{typ}_deadline_label"))
    return cols, vals


def _deadline_set_clause() -> str:
    """Build the ON CONFLICT DO UPDATE SET clause for all 4 deadline types."""
    set_parts = []
    for typ in DEADLINE_TYPES:
        for suffix in ["", "_label"]:
            field = f"{typ}_deadline{suffix}"
            set_parts.append(f"{field} = COALESCE(EXCLUDED.{field}, conferences.{field})")
    return ", ".join(set_parts)


def save_conference(conf: dict) -> tuple[bool, bool, int | None]:
    """Open a fresh DB connection, save conference, close immediately.

    Normalizes the website URL for consistent dedup.
    Returns (success, was_inserted, conf_id).
    success: True if DB write succeeded.
    was_inserted: True if a new row was inserted (not an update of an existing row).
    conf_id: The conference ID if the write succeeded, None otherwise.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        website = normalize_website(conf.get("website", ""))
        dl_cols, dl_vals = _deadline_columns(conf)
        dl_set = _deadline_set_clause()

        base_cols = ["title", "date_start", "date_end", "city", "country",
                     "website", "organizer", "category", "confidence", "raw_source", "is_notified"]
        all_cols = base_cols + dl_cols
        placeholders = ", ".join(["%s"] * len(all_cols))
        col_names = ", ".join(all_cols)

        sql = f"""
            INSERT INTO conferences ({col_names})
            VALUES ({placeholders})
            ON CONFLICT (website, date_start) DO UPDATE SET
                {dl_set},
                submission_deadline = NULL,
                submission_deadline_label = NULL,
                submission_deadline_2 = NULL,
                submission_deadline_2_label = NULL,
                submission_deadline_previous = NULL,
                submission_deadline_2_previous = NULL,
                updated_at = NOW()
            RETURNING created_at = updated_at AS inserted, id
        """

        base_vals = [
            conf.get("title"), conf.get("date_start"), conf.get("date_end"),
            conf.get("city"), "Bangladesh", website,
            conf.get("organizer"), conf.get("category"),
            conf.get("confidence"), conf.get("raw_source"), False,
        ]
        cur.execute(sql, base_vals + dl_vals)
        row = cur.fetchone()
        conn.commit()
        cur.close()
        was_inserted = bool(row and row[0])
        conf_id = row[1] if row else None
        return True, was_inserted, conf_id
    except Exception as e:
        logger.error("save_conference error: %s", e)
        return False, False, None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ── seen_links state machine (DFS — once terminal, never re-checked) ──


def mark_url_status(url: str, status: str) -> None:
    """Ensure URL exists in seen_links with the given terminal status.

    Uses INSERT ON CONFLICT so it works even if the URL was never
    previously inserted (e.g. URLs from crt_monitor which saves to
    known_subdomains, not seen_links).
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO seen_links (url, source, status) VALUES (%s, 'phase4', %s) "
            "ON CONFLICT (url) DO UPDATE SET status = %s, last_seen = NOW() "
            "WHERE seen_links.status NOT IN %s",
            (url, status, status, TERMINAL_STATUSES),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("mark_url_status error for %s: %s", url, e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def is_url_processed(url: str) -> bool:
    """Check if a URL is already in a terminal state (never re-check).

    Returns True if the URL has been fully evaluated:
    - not_conference: LLM said no
    - low_confidence: below threshold
    - extracted: conference saved and notified
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM seen_links WHERE url = %s", (url,)
        )
        row = cur.fetchone()
        cur.close()
        if row is None:
            return False  # new URL, not yet seen
        return row[0] in TERMINAL_STATUSES
    except Exception as e:
        logger.error("is_url_processed error for %s: %s", url, e)
        return False  # on error, let it be processed (safer)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def load_pending_urls() -> list:
    """Load all URLs in seen_links that still need processing.

    Returns URLs with status = 'pending' (discovered but not yet extracted).
    URLs in terminal states (not_conference, low_confidence, extracted)
    are never returned — they are done forever.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT url FROM seen_links WHERE status = 'pending'"
        )
        urls = [row[0] for row in cur.fetchall()]
        cur.close()
        return urls
    except Exception as e:
        logger.error("load_pending_urls error: %s", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ── Retry bookkeeping for failed_transient URLs ──

MAX_RETRIES = 3
RETRY_BACKOFF_HOURS = [6, 24, 72]


def load_retryable_urls() -> list:
    """Load failed_transient URLs eligible for retry with widening backoff.

    URLs that exhaust retries are demoted to failed_permanent (terminal).
    Returns list of (url, retry_count) for URLs whose backoff window has elapsed.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT url, retry_count, last_attempt_at FROM seen_links "
            "WHERE status = 'failed_transient'"
        )
        now = datetime.now(timezone.utc)
        retryable = []
        for url, retry_count, last_attempt_at in cur.fetchall():
            if retry_count >= MAX_RETRIES:
                logger.warning("Retries exhausted for %s, demoting to failed_permanent", url)
                mark_url_status(url, "failed_permanent")
                continue
            if last_attempt_at is None:
                retryable.append((url, retry_count))
                continue
            hours_since = (now - last_attempt_at).total_seconds() / 3600
            if hours_since >= RETRY_BACKOFF_HOURS[retry_count]:
                retryable.append((url, retry_count))
        cur.close()
        return retryable
    except Exception as e:
        logger.error("load_retryable_urls error: %s", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def increment_retry(url: str) -> None:
    """Increment retry_count and set last_attempt_at for a URL."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE seen_links SET retry_count = COALESCE(retry_count, 0) + 1, "
            "last_attempt_at = NOW() WHERE url = %s", (url,)
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("increment_retry error for %s: %s", url, e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def mark_notified_with_retry(conf_id: int, max_attempts: int = 3) -> bool:
    """Mark a conference as notified with retry logic to prevent duplicate notifications."""
    for attempt in range(max_attempts):
        conn = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE id = %s",
                (conf_id,)
            )
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            logger.error(
                "mark_notified attempt %d/%d failed for id=%d: %s",
                attempt + 1, max_attempts, conf_id, e
            )
            time.sleep(2)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    logger.critical(
        "mark_notified FAILED all %d attempts for id=%d "
        "— DUPLICATE NOTIFICATION RISK on next run",
        max_attempts, conf_id
    )
    return False


def load_known_websites() -> set:
    """Load all conference website URLs already saved in the DB.

    Used to skip extraction for URLs that would produce duplicates.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT website FROM conferences")
        websites = {normalize_website(row[0]) for row in cur.fetchall() if row[0]}
        cur.close()
        return websites
    except Exception as e:
        logger.error("load_known_websites error: %s", e)
        return set()
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def mark_verification_done() -> None:
    """Record the last deadline-verification run as a timestamp."""
    now = datetime.now(timezone.utc)
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO daily_tasks (task_name, last_run_date)
            VALUES ('deadline_verification', %s)
            ON CONFLICT (task_name) DO UPDATE SET last_run_date = %s
            """,
            (now, now)
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("mark_verification_done error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
