import logging
import os
import re
import sys
import time
from datetime import datetime, date
from urllib.parse import urlparse, urlunparse

import requests

from db import get_connection, TERMINAL_STATUSES
from sources import homepage_links, special
from extractor import extract, daily_quota_exhausted, total_requests_today
from schema import DEADLINE_TYPES, DEADLINE_LABELS
from validation import (
    _parse_date_safe, _check_deadline_swap,
    _check_chronological_order, _check_deadline_context,
)
from notifier import notify
from browser import PlaywrightManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── URL normalization for consistent dedup ──


def _normalize_website(url: str) -> str:
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


# ── DB helpers — each opens, uses, and closes its own connection in <1s ──


def _build_deadline_cols(conf: dict) -> tuple[list[str], list]:
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


def _build_deadline_set_clause() -> str:
    """Build the ON CONFLICT DO UPDATE SET clause for all 4 deadline types."""
    set_parts = []
    for typ in DEADLINE_TYPES:
        for suffix in ["", "_label"]:
            field = f"{typ}_deadline{suffix}"
            set_parts.append(f"{field} = COALESCE(EXCLUDED.{field}, conferences.{field})")
    return ", ".join(set_parts)


def _save_conference(conf: dict) -> tuple[bool, bool, int | None]:
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
        website = _normalize_website(conf.get("website", ""))
        dl_cols, dl_vals = _build_deadline_cols(conf)
        dl_set = _build_deadline_set_clause()

        base_cols = ["title", "date_start", "date_end", "city", "country",
                     "website", "organizer", "category", "confidence", "raw_source", "is_notified"]
        all_cols = base_cols + dl_cols
        placeholders = ", ".join(f"%s" for _ in all_cols)
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
        websites = {_normalize_website(row[0]) for row in cur.fetchall() if row[0]}
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


# ── Retry logic for failed_transient URLs ──

MAX_RETRIES = 3
RETRY_BACKOFF_HOURS = [6, 24, 72]


def _load_retryable_urls() -> list:
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
        now = datetime.now()
        retryable = []
        for url, retry_count, last_attempt_at in cur.fetchall():
            if retry_count >= MAX_RETRIES:
                logger.warning("Retries exhausted for %s, demoting to failed_permanent", url)
                _mark_url_status(url, "failed_permanent")
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
        logger.error("_load_retryable_urls error: %s", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _increment_retry(url: str) -> None:
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
        logger.error("_increment_retry error for %s: %s", url, e)
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

    dl_date_checks = []
    dl_select_cols = []
    for typ in DEADLINE_TYPES:
        dl_select_cols.append(f"{typ}_deadline")
        dl_select_cols.append(f"{typ}_deadline_label")
        dl_date_checks.append(
            f"({typ}_deadline IS NOT NULL"
            f" AND {typ}_deadline >= CURRENT_DATE"
            f" AND {typ}_deadline <= CURRENT_DATE + INTERVAL '30 days')"
        )

    # Also check legacy columns for conferences that haven't been re-extracted yet
    dl_date_checks.append(
        "(submission_deadline IS NOT NULL"
        " AND submission_deadline >= CURRENT_DATE"
        " AND submission_deadline <= CURRENT_DATE + INTERVAL '30 days')"
    )
    dl_date_checks.append(
        "(submission_deadline_2 IS NOT NULL"
        " AND submission_deadline_2 >= CURRENT_DATE"
        " AND submission_deadline_2 <= CURRENT_DATE + INTERVAL '30 days')"
    )

    select_dl = ", ".join(dl_select_cols)
    date_or_clause = " OR ".join(dl_date_checks)

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, title, date_start, date_end, city, website,
                   organizer, category, confidence,
                   {select_dl}
            FROM conferences
            WHERE is_notified = FALSE
              AND (date_start IS NULL OR date_start >= CURRENT_DATE)
              AND ({date_or_clause})
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
            # Map the 8 deadline fields (date + label for each type)
            dl_offset = 9
            for i, typ in enumerate(DEADLINE_TYPES):
                date_col_idx = dl_offset + i * 2
                label_col_idx = dl_offset + i * 2 + 1
                conf[f"{typ}_deadline"] = str(row[date_col_idx]) if row[date_col_idx] else None
                conf[f"{typ}_deadline_label"] = row[label_col_idx]

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
    Runs at most once per day (guarded by daily_tasks table).
    If a deadline changed, updates the DB and
    sends a Telegram notification about the extension/change.
    Only processes conferences with date_start > today.
    Only checks conferences with at least one non-null deadline.
    """
    # Once-per-day guard using daily_tasks
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

    # Build deadline column names for SELECT — we need both old legacy fields and new named fields
    dl_select_cols = []
    dl_date_checks = []
    for typ in DEADLINE_TYPES:
        dl_select_cols.append(f"{typ}_deadline")
        dl_select_cols.append(f"{typ}_deadline_label")
        dl_date_checks.append(
            f"({typ}_deadline IS NOT NULL"
            f" AND {typ}_deadline >= CURRENT_DATE - INTERVAL '30 days'"
            f" AND {typ}_deadline <= CURRENT_DATE + INTERVAL '30 days')"
        )

    # Also include legacy fields in the check
    dl_date_checks.append(
        "(submission_deadline IS NOT NULL"
        " AND submission_deadline >= CURRENT_DATE - INTERVAL '30 days'"
        " AND submission_deadline <= CURRENT_DATE + INTERVAL '30 days')"
    )
    dl_date_checks.append(
        "(submission_deadline_2 IS NOT NULL"
        " AND submission_deadline_2 >= CURRENT_DATE - INTERVAL '30 days'"
        " AND submission_deadline_2 <= CURRENT_DATE + INTERVAL '30 days')"
    )

    select_dl = ", ".join(dl_select_cols)
    date_or_clause = " OR ".join(dl_date_checks)

    conn = None
    conferences = []
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, title, website,
                   submission_deadline, submission_deadline_label,
                   submission_deadline_2, submission_deadline_2_label,
                   {select_dl}
            FROM conferences
            WHERE date_start > CURRENT_DATE
              AND ({date_or_clause})
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

    # Build the allowed fields set for SQL injection protection
    _ALLOWED_FIELDS = set()
    for typ in DEADLINE_TYPES:
        _ALLOWED_FIELDS.add(f"{typ}_deadline")
        _ALLOWED_FIELDS.add(f"{typ}_deadline_label")
        _ALLOWED_FIELDS.add(f"{typ}_deadline_previous")

    for row in conferences:
        conf_id = row[0]
        title = row[1]
        website = row[2]
        # Legacy fields
        leg_dl1 = row[3]
        leg_label1 = row[4]
        leg_dl2 = row[5]
        leg_label2 = row[6]

        # Build old values dict from named columns (falling back to legacy)
        old_values = {}
        dl_offset = 7
        for i, typ in enumerate(DEADLINE_TYPES):
            named_dl = row[dl_offset + i * 2]
            named_label = row[dl_offset + i * 2 + 1]
            old_values[typ] = {
                "date": named_dl if named_dl else (leg_dl1 if i == 0 else (leg_dl2 if i == 1 else None)),
                "label": named_label if named_label else (leg_label1 if i == 0 else (leg_label2 if i == 1 else None)),
            }

        try:
            # Re-extract using shared browser instance
            result = extract(website, playwright)
            if not result or not result.get("is_conference"):
                logger.warning(
                    "deadline_verification: could not re-extract %s", website
                )
                continue

            # ── Validation layers ──
            new_values = {}
            for typ in DEADLINE_TYPES:
                new_values[typ] = _parse_date_safe(result.get(f"{typ}_deadline"))

            stored_values = {}
            for typ in DEADLINE_TYPES:
                stored_values[typ] = old_values[typ]["date"]

            # Layer A: cross-field swap detection
            swapped_fields = _check_deadline_swap(new_values, stored_values)

            # Layer B: chronological order constraint
            conf_start = _parse_date_safe(result.get("date_start"))
            if not _check_chronological_order(new_values, conf_start):
                logger.warning(
                    "deadline_verification: %s — chronological order violated, "
                    "skipping entire re-verification",
                    website
                )
                continue

            # Layer C: context keyword validation
            context_mismatches = _check_deadline_context(result)

            # Build list of fields that changed or are newly discovered
            updates = []
            notify_changes = []

            # Check each named deadline type independently
            for typ in DEADLINE_TYPES:
                if typ in swapped_fields:
                    logger.warning(
                        "deadline_verification: %s — %s swapped, skipping",
                        website, typ
                    )
                    continue

                if typ in context_mismatches:
                    logger.warning(
                        "deadline_verification: %s — %s context mismatch, skipping",
                        website, typ
                    )
                    continue

                new_dl_str = result.get(f"{typ}_deadline")
                if not new_dl_str:
                    continue  # LLM didn't find this deadline type on the page

                new_dl = _parse_date_safe(new_dl_str)
                new_label = result.get(f"{typ}_deadline_label") or DEADLINE_LABELS.get(typ, typ.replace("_", " ").title())
                old_dl = old_values[typ]["date"]

                if new_dl and new_dl != old_dl:
                    if old_dl is not None and new_dl < old_dl:
                        logger.warning(
                            "deadline_verification: %s — %s moved backward %s → %s, "
                            "likely extraction error, skipping",
                            website, typ, old_dl, new_dl
                        )
                        continue

                    field = f"{typ}_deadline"
                    label_field = f"{typ}_deadline_label"
                    prev_field = f"{typ}_deadline_previous"
                    updates.append((field, label_field, prev_field, new_dl, new_label))
                    if old_dl is not None:
                        notify_changes.append({"old": old_dl, "new": new_dl,
                                               "label": new_label})
                    else:
                        logger.info(
                            "deadline_verification: %s — first %s found: %s",
                            website, field, new_dl
                        )

            if not updates:
                logger.info(
                    "deadline_verification: %s — no change", website
                )
                continue

            # Always save new/changed deadlines to DB
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

            # Re-queue retryable URLs (status='failed_transient', backoff elapsed)
            retryable = _load_retryable_urls()
            retryable_urls = [url for url, _ in retryable]
            retryable_url_set = set(retryable_urls)
            if retryable_urls:
                all_candidates = list(set(retryable_urls + all_candidates))
                logger.info("Re-queued %d retryable URLs from previous runs", len(retryable_urls))

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
                # Increment retry counter before retrying a failed_transient URL
                if url in retryable_url_set:
                    _increment_retry(url)
                # Detect root_year-tagged URLs from special sources
                # Format: "root_year:{year}:{actual_url}"
                root_year_info = None
                actual_url = url
                if url.startswith("root_year:"):
                    parts = url.split(":", 2)
                    root_year_info = (parts[2], int(parts[1]))
                    actual_url = parts[2]
                    url = actual_url

                # Root_year already verified by _is_edition_in_db — skip URL-processed check
                if not root_year_info and _is_url_processed(url):
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
                # Root_year sources already verified by _is_edition_in_db — skip this check
                if not root_year_info and _normalize_website(url) in known_websites:
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
                    _mark_url_status(url, "failed_transient")
                    failed += 1
                    time.sleep(5)
                    continue

                if result is None:
                    if daily_quota_exhausted():
                        quota_exhausted = True
                    logger.warning("Extraction failed for: %s", url)
                    _mark_url_status(url, "failed_transient")
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

                if not root_year_info and _normalize_website(result.get("website", "")) in known_websites:
                    logger.info("Duplicate conference, marking done: %s", url)
                    _mark_url_status(url, "extracted")
                    skipped += 1
                    time.sleep(5)
                    continue

                # Layer B: chronological order constraint
                conf_start = _parse_date_safe(result.get("date_start"))
                new_values = {}
                for typ in DEADLINE_TYPES:
                    new_values[typ] = _parse_date_safe(result.get(f"{typ}_deadline"))
                if not _check_chronological_order(new_values, conf_start):
                    logger.warning(
                        "Chronological order violated at %s, retry next run", url
                    )
                    _mark_url_status(url, "failed_transient")
                    failed += 1
                    time.sleep(5)
                    continue

                # Layer C: context validation
                context_mismatches = _check_deadline_context(result)
                if context_mismatches:
                    logger.warning(
                        "Context mismatch for fields %s at %s, retry next run",
                        context_mismatches, url
                    )
                    _mark_url_status(url, "failed_transient")
                    failed += 1
                    time.sleep(5)
                    continue

                result["raw_source"] = url
                save_success, was_inserted, conf_id = _save_conference(result)
                if not save_success:
                    # DB write failed — do NOT mark as terminal
                    # Leave URL as-is so next run retries
                    failed += 1
                    time.sleep(5)
                    continue

                _mark_url_status(url, "extracted")

                if was_inserted:
                    logger.info("New conference saved: %s", result.get("title"))

                    # Only notify if at least one deadline is within 30 days
                    should_notify = True
                    now_date = datetime.now().date()
                    any_within_30 = False
                    for typ in DEADLINE_TYPES:
                        dl_str = result.get(f"{typ}_deadline")
                        if dl_str:
                            try:
                                dl_date = datetime.strptime(dl_str, "%Y-%m-%d").date()
                                days_until_dl = (dl_date - now_date).days
                                if 0 <= days_until_dl <= 30:
                                    any_within_30 = True
                                    break
                            except (ValueError, TypeError):
                                pass

                    if not any_within_30:
                        logger.info(
                            "No deadline within 30 days — "
                            "saving but NOT notifying yet: %s",
                            result.get("title")
                        )
                        should_notify = False

                    if should_notify and conf_id:
                        notify(result)
                        _mark_notified_with_retry(conf_id)
                    else:
                        logger.info(
                            "Conference saved (not yet notified): %s — "
                            "will notify when deadline is within 30 days",
                            result.get("title")
                        )
                    new_count += 1
                else:
                    logger.info("Conference already in DB (updated deadlines): %s", result.get("title"))
                    skipped += 1

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
