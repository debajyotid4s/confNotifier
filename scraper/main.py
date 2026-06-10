import logging
import os
import sys
import time
from datetime import datetime

import psycopg2
import requests

from db import get_connection, save_seen_link
from sources import crt_monitor, homepage_links, special
from extractor import extract, daily_quota_exhausted, total_requests_today
from notifier import notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── DB helpers — each opens, uses, and closes its own connection in <1s ──


def _save_conference(conf: dict) -> bool:
    """Open a fresh DB connection, save conference, close immediately."""
    conn = None
    try:
        conn = get_connection()
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


def _is_duplicate(website: str) -> bool:
    """Open a fresh DB connection, check duplicate, close immediately."""
    conn = None
    try:
        conn = get_connection()
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


def _mark_url_status(url: str, status: str) -> None:
    """Update only the status of an already-seen URL."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE seen_links SET status = %s, last_seen = NOW() WHERE url = %s",
            (status, url),
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


def _is_url_processed(url: str) -> bool:
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
        return row[0] in ("not_conference", "low_confidence", "extracted")
    except Exception as e:
        logger.error("is_url_processed error for %s: %s", url, e)
        return False  # on error, let it be processed (safer)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _load_pending_urls() -> list:
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

    # Mark all past conferences as notified (cleanup from before date filter)
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE conferences SET is_notified = TRUE, notified_at = NOW() "
            "WHERE is_notified = FALSE AND date_start < CURRENT_DATE"
        )
        if cur.rowcount > 0:
            logger.info("notify_pending: marked %d past conferences as notified", cur.rowcount)
        conn.commit()
        cur.close()
        conn.close()
        conn = None
    except Exception as e:
        logger.error("notify_pending: cleanup error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, date_start, date_end, city, website,
                   organizer, category, confidence
            FROM conferences
            WHERE is_notified = FALSE
              AND (date_start IS NULL OR date_start >= CURRENT_DATE)
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
                    conn2 = get_connection()
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
                time.sleep(2)  # avoid burst spam
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
    for var in ["DATABASE_URL", "GOOGLE_AI_KEY", "TELEGRAM_BOT_TOKEN"]:
        if var not in os.environ or not os.environ[var].strip():
            print(f"ERROR: Missing or empty environment variable: {var}")
            print(f"  Set it in GitHub repo -> Settings -> Secrets -> Actions")
            sys.exit(1)
        logger.info("Env var %s: set (%s...)", var, os.environ[var][:8])

    if not (os.environ.get("TELEGRAM_CHANNEL_ID", "").strip() or
            os.environ.get("TELEGRAM_CHANNEL_LINK", "").strip()):
        print("ERROR: Missing environment variable: TELEGRAM_CHANNEL_ID or TELEGRAM_CHANNEL_LINK")
        sys.exit(1)

    # Connectivity test — verify DB is reachable, then close immediately
    try:
        conn = get_connection()
        conn.close()
        logger.info("Connected to PostgreSQL")
    except Exception as e:
        logger.critical("Cannot connect to PostgreSQL: %s", e)
        sys.exit(1)

    # Verify bot can access the Telegram channel
    try:
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        channel = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_LINK", "")
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": channel},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Telegram channel access verified")
        else:
            logger.warning("Telegram channel check failed (%d): %s", resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Telegram channel check error: %s", e)

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

    # Re-queue pending URLs from previous runs (status='pending', not yet extracted)
    pending_prev = _load_pending_urls()
    if pending_prev:
        all_candidates = list(set(pending_prev + all_candidates))
        logger.info("Re-queued %d pending URLs from previous runs", len(pending_prev))

    logger.info("Phase 4: Processing %d unique candidates", len(all_candidates))

    found = len(all_candidates)
    new_count = 0
    skipped = 0
    failed = 0
    quota_exhausted = False

    for url in all_candidates:
        # DFS: skip URLs already in terminal state (never re-check)
        if _is_url_processed(url):
            logger.debug("Already processed, skipping: %s", url)
            skipped += 1
            continue

        if quota_exhausted:
            # Quota exhausted — remaining URLs stay pending, auto-retried next run
            remaining = all_candidates[all_candidates.index(url):]
            logger.warning(
                "Daily quota exhausted — %d URLs remain pending for next run",
                len(remaining)
            )
            break

        logger.info("Extracting data from: %s", url)
        try:
            result = extract(url)
        except RuntimeError as e:
            if "Daily quota exhausted" in str(e):
                quota_exhausted = True
                logger.warning("Daily quota exhausted, stopping extraction")
                time.sleep(5)
                continue
            logger.error("Unexpected error for %s: %s", url, e)
            _mark_url_status(url, "failed")
            failed += 1
            time.sleep(5)
            continue

        if result is None:
            if daily_quota_exhausted():
                quota_exhausted = True
            logger.warning("Extraction failed for: %s", url)
            _mark_url_status(url, "failed")
            failed += 1
            time.sleep(5)
            continue

        if not result.get("is_conference", False):
            logger.info("Not a conference, marking done: %s", url)
            _mark_url_status(url, "not_conference")
            skipped += 1
            time.sleep(5)
            continue

        # Skip low-confidence extractions
        MIN_CONFIDENCE = 0.75
        if result.get("confidence", 0) < MIN_CONFIDENCE:
            logger.warning(
                "Low confidence %.2f for %s, marking done",
                result.get("confidence"), url
            )
            _mark_url_status(url, "low_confidence")
            skipped += 1
            time.sleep(5)
            continue

        # Skip conferences that have already ended
        date_start = result.get("date_start")
        if date_start:
            try:
                conf_date = datetime.strptime(date_start, "%Y-%m-%d").date()
                if conf_date < datetime.now().date():
                    logger.info("Conference already past (%s), marking done: %s", date_start, url)
                    _mark_url_status(url, "not_conference")
                    skipped += 1
                    time.sleep(5)
                    continue
            except (ValueError, TypeError):
                pass

        if _is_duplicate(result.get("website", "")):
            logger.info("Duplicate conference, marking done: %s", url)
            _mark_url_status(url, "extracted")
            skipped += 1
            time.sleep(5)
            continue

        result["raw_source"] = url
        if not _save_conference(result):
            _mark_url_status(url, "failed")
            failed += 1
            time.sleep(5)
            continue

        logger.info("New conference saved: %s", result.get("title"))
        _mark_url_status(url, "extracted")
        notify(result)

        # Retry mark_notified up to 3 times to prevent duplicates
        for attempt in range(3):
            try:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE conferences SET is_notified=TRUE, notified_at=NOW() WHERE website=%s",
                    (result.get("website"),),
                )
                conn.commit()
                cur.close()
                conn.close()
                break
            except Exception as e:
                logger.error("Failed to mark notified (attempt %d): %s", attempt + 1, e)
                time.sleep(2)

        new_count += 1
        time.sleep(5)

    logger.info(
        "=== Run complete: %d found, %d new, %d skipped, %d failed | "
        "LLM requests today: %d ===",
        found, new_count, skipped, failed,
        total_requests_today()
    )

    # Notify any conferences saved but not yet notified
    # (includes backlog from previous runs and current run)
    pending_sent = _notify_pending(notify)
    if pending_sent > 0:
        logger.info("notify_pending: sent %d notification(s)", pending_sent)


if __name__ == "__main__":
    run()
