import logging
import os
import sys
from datetime import datetime

import psycopg2

from sources import crt_monitor, homepage_links, special
from extractor import extract, _rate_limiter
from notifier import notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── DB helpers — each opens, uses, and closes its own connection in <1s ──


def _db_url():
    return os.environ["DATABASE_URL"]


def _save_conference(conf: dict) -> bool:
    """Open a fresh DB connection, save conference, close immediately."""
    conn = None
    try:
        conn = psycopg2.connect(_db_url())
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO conferences
                (title, date_start, date_end, city, country, website,
                 organizer, category, confidence, raw_source, is_notified)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (website) DO NOTHING
            """,
            (
                conf.get("title"), conf.get("date_start"), conf.get("date_end"),
                conf.get("city"), "Bangladesh", conf.get("website"),
                conf.get("organizer"), conf.get("category"),
                conf.get("confidence"), conf.get("raw_source"), False,
            )
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        logger.error("save_conference error: %s", e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _mark_extracted(subdomain: str) -> None:
    """Open a fresh DB connection, mark subdomain extracted, close immediately."""
    conn = None
    try:
        conn = psycopg2.connect(_db_url())
        cur = conn.cursor()
        cur.execute(
            "UPDATE known_subdomains SET extracted = TRUE WHERE subdomain = %s",
            (subdomain.replace("https://", "").replace("http://", ""),)
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("mark_extracted error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _is_duplicate(website: str) -> bool:
    """Open a fresh DB connection, check duplicate, close immediately."""
    conn = None
    try:
        conn = psycopg2.connect(_db_url())
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM conferences WHERE website = %s", (website,)
        )
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception as e:
        logger.error("is_duplicate error: %s", e)
        return False   # assume not duplicate on error — safer to attempt save
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _save_seen_link(url: str, source: str = "extracted") -> None:
    """Open a fresh DB connection, save link, close immediately."""
    conn = None
    try:
        conn = psycopg2.connect(_db_url())
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO seen_links (url, source) VALUES (%s, %s) "
            "ON CONFLICT (url) DO UPDATE SET source = %s, last_seen = NOW()",
            (url, source, source),
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


def _load_unextracted_urls() -> list:
    """Open a fresh DB connection, load unextracted URLs, close immediately."""
    conn = None
    try:
        conn = psycopg2.connect(_db_url())
        cur = conn.cursor()
        cur.execute("SELECT url FROM seen_links WHERE source = 'unextracted'")
        urls = [row[0] for row in cur.fetchall()]
        cur.close()
        return urls
    except Exception as e:
        logger.error("load_unextracted_urls error: %s", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _load_orphaned_urls() -> list:
    """Load URLs in seen_links that have no matching conference entry.

    These are URLs that were probed successfully but extraction failed
    (rate limit, LLM error, short page, etc.) in a previous run.
    They need to be re-processed.
    """
    conn = None
    try:
        conn = psycopg2.connect(_db_url())
        cur = conn.cursor()
        cur.execute(
            """
            SELECT sl.url FROM seen_links sl
            LEFT JOIN conferences c
              ON sl.url = c.raw_source OR sl.url = c.website
            WHERE c.id IS NULL
              AND sl.source != 'unextracted'
              AND sl.url NOT LIKE '%%#%%'
            """
        )
        urls = [row[0] for row in cur.fetchall()]
        cur.close()
        return urls
    except Exception as e:
        logger.error("load_orphaned_urls error: %s", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _mark_notified(website: str) -> None:
    """Open a fresh DB connection, mark conference notified, close immediately."""
    conn = None
    try:
        conn = psycopg2.connect(_db_url())
        cur = conn.cursor()
        cur.execute(
            "UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE website = %s",
            (website,),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("mark_notified error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _notify_pending(notify_fn) -> int:
    """
    Send Telegram notifications for all conferences where is_notified = FALSE.

    Opens a fresh DB connection per operation to avoid Neon idle timeout.
    Returns the count of successfully notified conferences.

    This runs at the end of every scraper run and catches:
    - Conferences saved in a previous run where notification crashed
    - Conferences saved in the current run's Phase 4 loop
    - Any backlog that accumulated during debugging/development
    """
    conn = None
    notified_count = 0

    try:
        conn = psycopg2.connect(_db_url())
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, date_start, date_end, city, website,
                   organizer, category, confidence
            FROM conferences
            WHERE is_notified = FALSE
            ORDER BY created_at ASC
            """
        )
        pending = cur.fetchall()
        cur.close()
        conn.close()
        conn = None

        if not pending:
            logger.info("notify_pending: no unnotified conferences found")
            return 0

        logger.info(
            "notify_pending: found %d conference(s) to notify", len(pending)
        )

        for row in pending:
            conf_id = row[0]
            conf = {
                "title":      row[1],
                "date_start": str(row[2]) if row[2] else None,
                "date_end":   str(row[3]) if row[3] else None,
                "city":       row[4],
                "website":    row[5],
                "organizer":  row[6],
                "category":   row[7],
                "confidence": row[8],
            }

            try:
                success = notify_fn(conf)
            except Exception as e:
                logger.error(
                    "notify_pending: notify_fn raised for id=%d (%s): %s",
                    conf_id, conf.get("website"), e
                )
                success = False

            if success:
                conn2 = None
                try:
                    conn2 = psycopg2.connect(_db_url())
                    cur2 = conn2.cursor()
                    cur2.execute(
                        """
                        UPDATE conferences
                        SET is_notified = TRUE, notified_at = NOW()
                        WHERE id = %s
                        """,
                        (conf_id,)
                    )
                    conn2.commit()
                    cur2.close()
                    notified_count += 1
                    logger.info(
                        "notify_pending: notified id=%d — %s",
                        conf_id, conf.get("title")
                    )
                except Exception as e:
                    logger.error(
                        "notify_pending: failed to mark id=%d as notified: %s",
                        conf_id, e
                    )
                finally:
                    if conn2:
                        try:
                            conn2.close()
                        except Exception:
                            pass
            else:
                logger.warning(
                    "notify_pending: notify_fn returned False for id=%d (%s), "
                    "will retry next run",
                    conf_id, conf.get("website")
                )

    except Exception as e:
        logger.error("notify_pending: error fetching pending conferences: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return notified_count


# ── Main orchestrator ──


def run():
    """Main orchestrator: discover, extract, deduplicate, notify.

    Every DB operation opens and closes its own connection.
    No long-lived connection is held during source scanning or LLM extraction.
    """
    for var in ["DATABASE_URL", "GOOGLE_AI_KEY"]:
        if var not in os.environ or not os.environ[var].strip():
            print(f"ERROR: Missing or empty environment variable: {var}")
            print(f"  Set it in GitHub repo → Settings → Secrets → Actions")
            sys.exit(1)
        logger.info("Env var %s: set (%s...)", var, os.environ[var][:8])

    # Connectivity test — verify DB is reachable, then close immediately
    try:
        conn = psycopg2.connect(_db_url())
        conn.close()
        logger.info("Connected to PostgreSQL")
    except Exception as e:
        logger.critical("Cannot connect to PostgreSQL: %s", e)
        sys.exit(1)

    logger.info("=== BD Conference Bot Run Started ===")

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

    # Re-queue URLs from previous runs that were skipped due to quota
    unextracted_prev = _load_unextracted_urls()
    if unextracted_prev:
        all_candidates = list(set(unextracted_prev + all_candidates))
        logger.info("Re-queued %d unextracted URLs from previous runs", len(unextracted_prev))

    # Re-queue orphaned URLs (in seen_links but not in conferences — extraction failed previously)
    orphaned = _load_orphaned_urls()
    if orphaned:
        all_candidates = list(set(orphaned + all_candidates))
        logger.info("Re-queued %d orphaned URLs (seen but never extracted)", len(orphaned))

    logger.info("Phase 4: Processing %d unique candidates", len(all_candidates))

    found = len(all_candidates)
    new_count = 0
    skipped = 0
    failed = 0
    quota_exhausted = False

    for url in all_candidates:
        if quota_exhausted:
            remaining_urls = all_candidates[all_candidates.index(url):]
            logger.warning(
                "main: daily quota exhausted — marking %d remaining URLs as unextracted",
                len(remaining_urls)
            )
            for pending_url in remaining_urls:
                _save_seen_link(pending_url, source="unextracted")
            break

        logger.info("Extracting data from: %s", url)
        try:
            result = extract(url)
        except RuntimeError as e:
            if "Daily quota exhausted" in str(e):
                quota_exhausted = True
                _save_seen_link(url, source="unextracted")
                logger.warning("main: daily quota exhausted, stopping extraction")
                continue
            logger.error("main: unexpected error for %s: %s", url, e)
            failed += 1
            continue

        if result is None:
            if _rate_limiter.daily_quota_exhausted():
                quota_exhausted = True
                _save_seen_link(url, source="unextracted")
            logger.warning("Extraction failed for: %s", url)
            failed += 1
            continue

        if not result.get("is_conference", False):
            logger.info("Not a conference, skipping: %s", url)
            _save_seen_link(url)
            skipped += 1
            continue

        # Skip conferences that have already ended
        date_start = result.get("date_start")
        if date_start:
            try:
                conf_date = datetime.strptime(date_start, "%Y-%m-%d").date()
                if conf_date < datetime.now().date():
                    logger.info("Conference already past (%s), skipping: %s", date_start, url)
                    _save_seen_link(url)
                    skipped += 1
                    continue
            except (ValueError, TypeError):
                pass

        if _is_duplicate(result.get("website", "")):
            logger.info("Duplicate conference, skipping: %s", url)
            skipped += 1
            continue

        result["raw_source"] = url
        if not _save_conference(result):
            failed += 1
            continue

        logger.info("New conference saved: %s", result.get("title"))
        _mark_extracted(url)
        notify(result)
        new_count += 1

    logger.info(
        "=== Run complete: %d found, %d new, %d skipped, %d failed | "
        "LLM requests today: %d/%d ===",
        found, new_count, skipped, failed,
        _rate_limiter._daily_count, _rate_limiter.RPD_LIMIT
    )

    # Notify any conferences saved but not yet notified
    # (includes backlog from previous runs and current run)
    pending_sent = _notify_pending(notify)
    if pending_sent > 0:
        logger.info("notify_pending: sent %d notification(s)", pending_sent)


if __name__ == "__main__":
    run()
