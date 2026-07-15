import logging
import os
import re
import sys
import time
from datetime import datetime, date
from urllib.parse import urlparse

import requests

from db import get_connection, TERMINAL_STATUSES
from sources import homepage_links, special
from extractor import extract, daily_quota_exhausted, total_requests_today
from notifier import notify
from browser import PlaywrightManager

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
                 organizer, category, confidence, submission_deadline,
                 submission_deadline_label, submission_deadline_2,
                 submission_deadline_2_label, raw_source, is_notified)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (website) DO UPDATE SET
                submission_deadline = COALESCE(EXCLUDED.submission_deadline, conferences.submission_deadline),
                submission_deadline_label = COALESCE(EXCLUDED.submission_deadline_label, conferences.submission_deadline_label),
                submission_deadline_2 = COALESCE(EXCLUDED.submission_deadline_2, conferences.submission_deadline_2),
                submission_deadline_2_label = COALESCE(EXCLUDED.submission_deadline_2_label, conferences.submission_deadline_2_label),
                updated_at = NOW()
            """,
            (
                conf.get("title"), conf.get("date_start"), conf.get("date_end"),
                conf.get("city"), "Bangladesh", conf.get("website"),
                conf.get("organizer"), conf.get("category"),
                conf.get("confidence"), conf.get("submission_deadline"),
                conf.get("submission_deadline_label"), conf.get("submission_deadline_2"),
                conf.get("submission_deadline_2_label"), conf.get("raw_source"), False,
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


def _mark_url_status(url: str, status: str) -> None:
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


def _load_known_websites() -> set:
    """Load all conference website URLs already saved in the DB.

    Used to skip extraction for URLs that would produce duplicates.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT website FROM conferences")
        websites = {row[0] for row in cur.fetchall() if row[0]}
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
        return row[0] in ("not_conference", "low_confidence", "extracted", "failed")
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


def _mark_notified_with_retry(conf_id: int, max_attempts: int = 3) -> bool:
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


def _mark_notified_with_retry_by_website(website: str, max_attempts: int = 3) -> bool:
    """Mark a conference as notified by website URL with retry logic."""
    for attempt in range(max_attempts):
        conn = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE conferences SET is_notified = TRUE, notified_at = NOW() WHERE website = %s",
                (website,)
            )
            conn.commit()
            cur.close()
            return True
        except Exception as e:
            logger.error(
                "mark_notified attempt %d/%d failed for %s: %s",
                attempt + 1, max_attempts, website, e
            )
            time.sleep(2)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    logger.critical(
        "mark_notified FAILED all %d attempts for %s "
        "— DUPLICATE NOTIFICATION RISK on next run",
        max_attempts, website
    )
    return False


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
                   organizer, category, confidence,
                   submission_deadline, submission_deadline_label,
                   submission_deadline_2, submission_deadline_2_label
            FROM conferences
            WHERE is_notified = FALSE
              AND (date_start IS NULL OR date_start >= CURRENT_DATE)
              AND (
                  (submission_deadline IS NOT NULL
                   AND submission_deadline >= CURRENT_DATE
                   AND submission_deadline <= CURRENT_DATE + INTERVAL '30 days')
                  OR
                  (submission_deadline_2 IS NOT NULL
                   AND submission_deadline_2 >= CURRENT_DATE
                   AND submission_deadline_2 <= CURRENT_DATE + INTERVAL '30 days')
              )
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
                "submission_deadline": str(row[9]) if row[9] else None,
                "submission_deadline_label": row[10],
                "submission_deadline_2": str(row[11]) if row[11] else None,
                "submission_deadline_2_label": row[12],
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
                if _mark_notified_with_retry(conf_id):
                    notified_count += 1
                    logger.info(
                        "notify_pending: notified id=%d — %s",
                        conf_id, conf.get("title")
                    )
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


# ── Deadline re-verification (weekly) ──


def _parse_date_safe(date_str):
    """Parse a YYYY-MM-DD string to date, return None on failure."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(str(date_str))
    except (ValueError, TypeError):
        return None


def _mark_verification_done() -> None:
    """Mark deadline_verification as done today in daily_tasks."""
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
            (date.today(), date.today())
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("_mark_verification_done error: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _send_deadline_change_notification(title, website, changes) -> None:
    """Send a Telegram notification that a deadline has changed."""
    lines = []
    for change in changes:
        # Skip if old value is None — this is first-time discovery, not an update
        if not change["old"]:
            logger.warning(
                "deadline_verification: skipping notification for %s — old deadline is None",
                title
            )
            continue
        old_str = change["old"].strftime("%b %d")
        new_str = change["new"].strftime("%b %d") if change["new"] else "Unknown"
        lines.append(
            f"  <s>{old_str}</s> → <b>{new_str}</b> 📝 <i>Updated</i>"
        )

    if not lines:
        return

    updates_block = "\n".join(lines)

    message = (
        f"📢 <b>Deadline Updated</b>\n\n"
        f"<b>{_escape_html(title)}</b>\n\n"
        f"{updates_block}\n\n"
        f"🔗 <a href=\"{_escape_html(website)}\">{_escape_html(website)}</a>"
    )

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    channel = os.environ.get("TELEGRAM_CHANNEL_ID") or os.environ.get(
        "TELEGRAM_CHANNEL_LINK", ""
    )
    if channel.startswith("https://t.me/"):
        channel = "@" + channel.split("https://t.me/")[1]

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": channel,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info(
                "deadline_verification: sent change notification for %s", title
            )
        else:
            logger.error(
                "deadline_verification: Telegram failed (%d): %s",
                resp.status_code, resp.text
            )
    except Exception as e:
        logger.error(
            "deadline_verification: notification error for %s: %s", title, e
        )


def _verify_deadlines(playwright) -> None:
    """
    Re-extract submission deadlines for all upcoming conferences.
    Runs once per week. If a deadline changed, updates the DB and
    sends a Telegram notification about the extension/change.
    Only processes conferences with date_start > today.
    Only checks conferences with at least one non-null deadline.
    """
    # Once-per-week guard using daily_tasks
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT last_run_date FROM daily_tasks WHERE task_name = %s",
            ("deadline_verification",)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        conn = None

        today = date.today()
        if row and row[0]:
            days_since = (today - row[0]).days
            if days_since < 1:
                logger.info(
                    "deadline_verification: ran %d day(s) ago, skipping",
                    days_since
                )
                return
    except Exception as e:
        logger.error("deadline_verification: guard check error: %s", e)
        return
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    logger.info("deadline_verification: starting daily deadline re-check")

    # Load upcoming conferences with at least one deadline set
    conn = None
    conferences = []
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, website,
                   submission_deadline, submission_deadline_label,
                   submission_deadline_2, submission_deadline_2_label
            FROM conferences
            WHERE date_start > CURRENT_DATE
              AND (
                (submission_deadline IS NOT NULL
                 AND submission_deadline >= CURRENT_DATE - INTERVAL '30 days'
                 AND submission_deadline <= CURRENT_DATE + INTERVAL '30 days')
                OR
                (submission_deadline_2 IS NOT NULL
                 AND submission_deadline_2 >= CURRENT_DATE - INTERVAL '30 days'
                 AND submission_deadline_2 <= CURRENT_DATE + INTERVAL '30 days')
              )
            ORDER BY date_start ASC
            """
        )
        conferences = cur.fetchall()
        cur.close()
        conn.close()
        conn = None
    except Exception as e:
        logger.error("deadline_verification: failed to load conferences: %s", e)
        return
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    if not conferences:
        logger.info("deadline_verification: no upcoming conferences to check")
        _mark_verification_done()
        return

    logger.info(
        "deadline_verification: checking %d conference(s)", len(conferences)
    )

    for conf_id, title, website, dl1, label1, dl2, label2 in conferences:
        try:
            # Re-extract using shared browser instance
            result = extract(website, playwright)
            if not result or not result.get("is_conference"):
                logger.warning(
                    "deadline_verification: could not re-extract %s", website
                )
                continue

            new_dl1 = _parse_date_safe(result.get("submission_deadline"))
            new_dl2 = _parse_date_safe(result.get("submission_deadline_2"))
            new_label1 = result.get("submission_deadline_label") or label1
            new_label2 = result.get("submission_deadline_2_label") or label2

            # Build list of fields that changed or are newly discovered
            updates = []
            notify_changes = []

            # Check submission_deadline
            if new_dl1 and new_dl1 != dl1:
                updates.append(("submission_deadline", "submission_deadline_label",
                                "submission_deadline_previous", new_dl1, new_label1))
                # Only notify if old value existed (not first discovery)
                if dl1 is not None:
                    notify_changes.append({"old": dl1, "new": new_dl1,
                                           "label": new_label1 or "Submission Deadline"})
                else:
                    logger.info(
                        "deadline_verification: %s — first deadline found: %s",
                        website, new_dl1
                    )

            # Check submission_deadline_2
            if new_dl2 and new_dl2 != dl2:
                updates.append(("submission_deadline_2", "submission_deadline_2_label",
                                "submission_deadline_2_previous", new_dl2, new_label2))
                if dl2 is not None:
                    notify_changes.append({"old": dl2, "new": new_dl2,
                                           "label": new_label2 or "Deadline 2"})
                else:
                    logger.info(
                        "deadline_verification: %s — second deadline found: %s",
                        website, new_dl2
                    )

            if not updates:
                logger.info(
                    "deadline_verification: %s — no change", website
                )
                continue

            # Always save new/changed deadlines to DB
            # Whitelist of allowed field names to prevent SQL injection
            _ALLOWED_FIELDS = {
                "submission_deadline", "submission_deadline_label", "submission_deadline_previous",
                "submission_deadline_2", "submission_deadline_2_label", "submission_deadline_2_previous",
            }
            conn = None
            try:
                conn = get_connection()
                cur = conn.cursor()
                for field, label_field, prev_field, new_val, new_lbl in updates:
                    if field not in _ALLOWED_FIELDS or label_field not in _ALLOWED_FIELDS or prev_field not in _ALLOWED_FIELDS:
                        logger.error("deadline_verification: rejected unsafe field names for %s", website)
                        continue
                    cur.execute(
                        f"""
                        UPDATE conferences
                        SET {field} = %s,
                            {label_field} = %s,
                            {prev_field} = CASE
                                WHEN {field} IS NOT NULL AND {field} != %s THEN {field}
                                ELSE {prev_field}
                            END,
                            deadline_last_verified = NOW()
                        WHERE id = %s
                        """,
                        (new_val, new_lbl, new_val, conf_id)
                    )
                conn.commit()
                cur.close()
                logger.info(
                    "deadline_verification: updated %s — %d field(s) saved",
                    website, len(updates)
                )
            except Exception as e:
                logger.error(
                    "deadline_verification: DB update failed for %s: %s",
                    website, e
                )
                continue
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

            # Only send notification if there are actual changes (not first discoveries)
            if notify_changes:
                _send_deadline_change_notification(title, website, notify_changes)

        except Exception as e:
            logger.error(
                "deadline_verification: error processing %s: %s", website, e
            )
            continue

    _mark_verification_done()
    logger.info("deadline_verification: complete")


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

    homepage_candidates = []
    special_candidates = []

    try:
        with PlaywrightManager() as playwright:

            # Phase 1 — homepage scraping
            try:
                homepage_candidates = homepage_links.run(playwright=playwright)
                logger.info("homepage_links returned %d candidates", len(homepage_candidates))
            except Exception as e:
                logger.error("homepage_links failed: %s", e)
                homepage_candidates = []

            # Phase 2 — special sources
            try:
                special_candidates = special.run()
                logger.info("special returned %d candidates", len(special_candidates))
            except Exception as e:
                logger.error("special failed: %s", e)
                special_candidates = []

            all_candidates = list(
                set(homepage_candidates + special_candidates)
            )

            # Re-queue pending URLs from previous runs (status='pending', not yet extracted)
            pending_prev = _load_pending_urls()
            if pending_prev:
                all_candidates = list(set(pending_prev + all_candidates))
                logger.info("Re-queued %d pending URLs from previous runs", len(pending_prev))

            logger.info("Phase 4: Processing %d unique candidates", len(all_candidates))

            known_websites = _load_known_websites()
            if known_websites:
                logger.info("Loaded %d known conference websites for dedup", len(known_websites))

            found = len(all_candidates)
            new_count = 0
            skipped = 0
            failed = 0
            quota_exhausted = False

            for idx, url in enumerate(all_candidates):
                # DFS: skip URLs already in terminal state (never re-check)
                if _is_url_processed(url):
                    logger.debug("Already processed, skipping: %s", url)
                    skipped += 1
                    continue

                if quota_exhausted:
                    # Quota exhausted — remaining URLs stay pending, auto-retried next run
                    remaining = all_candidates[idx:]
                    logger.warning(
                        "Daily quota exhausted — %d URLs remain pending for next run",
                        len(remaining)
                    )
                    break

                # Pre-check 1: skip if conference website already in DB
                # (catches duplicates before wasting an LLM call)
                if url in known_websites:
                    logger.info("Duplicate (URL already known), skipping: %s", url)
                    _mark_url_status(url, "extracted")
                    skipped += 1
                    continue

                # Pre-check 2: skip URLs with past year in hostname
                # (e.g. icap2025.sust.edu when current year is 2026)
                hostname = urlparse(url).hostname or ""
                year_match = re.search(r"(\d{4})", hostname)
                if year_match:
                    url_year = int(year_match.group(1))
                    if url_year < datetime.now().year:
                        logger.info(
                            "Subdomain contains past year %d, skipping: %s",
                            url_year, url,
                        )
                        _mark_url_status(url, "not_conference")
                        skipped += 1
                        continue

                logger.info("Extracting data from: %s", url)
                try:
                    result = extract(url, playwright)
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

                if result.get("website", "") in known_websites:
                    logger.info("Duplicate conference, marking done: %s", url)
                    _mark_url_status(url, "extracted")
                    skipped += 1
                    time.sleep(5)
                    continue

                result["raw_source"] = url
                if not _save_conference(result):
                    # DB write failed — do NOT mark as terminal
                    # Leave URL as-is so next run retries
                    failed += 1
                    time.sleep(5)
                    continue

                logger.info("New conference saved: %s", result.get("title"))
                _mark_url_status(url, "extracted")

                # Only notify if submission deadline is within 30 days
                # (or no deadline extracted — discovery is still valuable)
                should_notify = True
                submission_dl = result.get("submission_deadline")
                if submission_dl:
                    try:
                        dl_date = datetime.strptime(submission_dl, "%Y-%m-%d").date()
                        days_until_dl = (dl_date - datetime.now().date()).days
                        if days_until_dl > 30:
                            logger.info(
                                "Submission deadline %s is %d days away — "
                                "saving but NOT notifying yet: %s",
                                submission_dl, days_until_dl, result.get("title")
                            )
                            should_notify = False
                        elif days_until_dl < 0:
                            logger.info(
                                "Submission deadline %s already past — "
                                "saving but NOT notifying: %s",
                                submission_dl, result.get("title")
                            )
                            should_notify = False
                    except (ValueError, TypeError):
                        pass

                if should_notify:
                    notify(result)
                    # Mark as notified (with retry to prevent duplicates)
                    _mark_notified_with_retry_by_website(result.get("website"))
                else:
                    logger.info(
                        "Conference saved (not yet notified): %s — "
                        "will notify when deadline is within 30 days",
                        result.get("title")
                    )

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

            # Phase 6: weekly deadline re-verification
            try:
                _verify_deadlines(playwright)
            except Exception as e:
                logger.error("deadline_verification: uncaught error: %s", e)

    except Exception as e:
        logger.critical("PlaywrightManager failed to launch — skipping browser-dependent phases: %s", e)
        logger.info("=== Run complete (partial — no browser): crt_monitor candidates only ===")


if __name__ == "__main__":
    run()
