import logging
import os
import sys

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


# ── Main orchestrator ──


def run():
    """Main orchestrator: discover, extract, deduplicate, notify.

    Every DB operation opens and closes its own connection.
    No long-lived connection is held during source scanning or LLM extraction.
    """
    for var in ["DATABASE_URL", "GOOGLE_AI_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID"]:
        if var not in os.environ or not os.environ[var].strip():
            print(f"ERROR: Missing or empty environment variable: {var}")
            sys.exit(1)

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

        if _is_duplicate(result.get("website", "")):
            logger.info("Duplicate conference, skipping: %s", url)
            skipped += 1
            continue

        result["raw_source"] = url
        if not _save_conference(result):
            failed += 1
            continue

        logger.info("New conference saved: %s", result.get("title"))

        if notify(result):
            _mark_notified(result.get("website"))   # use website as identifier

        new_count += 1
        _mark_extracted(url)

    logger.info(
        "=== Run complete: %d found, %d new, %d skipped, %d failed | "
        "LLM requests today: %d/%d ===",
        found, new_count, skipped, failed,
        _rate_limiter._daily_count, _rate_limiter.RPD_LIMIT
    )


if __name__ == "__main__":
    run()
