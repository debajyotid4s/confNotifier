"""Weekly deadline re-verification.

Re-extracts deadlines for upcoming conferences, updates the DB when a
deadline changed, and sends a Telegram notification about the change.
First-time discoveries save silently (no notification).
"""

import logging
from datetime import date

from scraper import db
from scraper.extractor import extract
from scraper.notifier import send_deadline_change_notification
from scraper.schema import (
    DEADLINE_TYPES,
    DEADLINE_LABELS,
    DEADLINE_DB_FIELDS,
    deadline_select_columns,
    deadline_range_checks,
)
from scraper.validation import (
    _parse_date_safe,
    _check_deadline_swap,
    _check_chronological_order,
    _check_deadline_context,
)

logger = logging.getLogger(__name__)

VERIFY_WINDOW_DAYS = 30
TASK_NAME = "deadline_verification"

# Whitelist of columns writable during verification (SQL injection guard).
ALLOWED_FIELDS = set(DEADLINE_DB_FIELDS)


def _should_run_verification() -> bool:
    """Once-per-day guard. Returns True when verification should run today."""
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT last_run_date FROM daily_tasks WHERE task_name = %s",
            (TASK_NAME,)
        )
        row = cur.fetchone()
        cur.close()

        today = date.today()
        if not row or not row[0]:
            return True
        days_since = (today - row[0]).days
        if days_since < 1:
            logger.info(
                "deadline_verification: ran %d day(s) ago, skipping",
                days_since
            )
            return False
        return True
    except Exception as e:
        logger.error("deadline_verification: guard check error: %s", e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _load_conferences_for_verification() -> list | None:
    """Load upcoming conferences with a deadline in the verify window.

    Returns a list of rows, or None on DB error (caller skips this run).
    """
    select_dl = ", ".join(deadline_select_columns())
    date_or_clause = " OR ".join(
        deadline_range_checks(VERIFY_WINDOW_DAYS, past_days=VERIFY_WINDOW_DAYS, include_legacy=True)
    )

    conn = None
    try:
        conn = db.get_connection()
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
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        logger.error("deadline_verification: failed to load conferences: %s", e)
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _extract_old_deadlines(row) -> dict:
    """Map a verification row to per-type {date, label}, falling back to legacy columns.

    Row layout: id, title, website, legacy_dl1, legacy_label1,
    legacy_dl2, legacy_label2, then date+label per DEADLINE_TYPES.
    """
    legacy_dates = {0: row[3], 1: row[5]}
    legacy_labels = {0: row[4], 1: row[6]}
    dl_offset = 7

    old = {}
    for i, typ in enumerate(DEADLINE_TYPES):
        named_date = row[dl_offset + i * 2]
        named_label = row[dl_offset + i * 2 + 1]
        old[typ] = {
            "date": named_date if named_date else legacy_dates.get(i),
            "label": named_label if named_label else legacy_labels.get(i),
        }
    return old


def _diff_deadlines(result: dict, old_values: dict, swapped_fields: set, context_mismatches: set, website: str):
    """Compare a fresh extraction against stored values.

    Returns (updates, notify_changes):
    - updates: list of (field, label_field, previous_field, new_date, new_label)
    - notify_changes: list of {"old", "new", "label"} — only real changes,
      not first-time discoveries.
    """
    updates = []
    notify_changes = []

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

        if not new_dl or new_dl == old_dl:
            continue

        if old_dl is not None and new_dl < old_dl:
            logger.warning(
                "deadline_verification: %s — %s moved backward %s → %s, "
                "likely extraction error, skipping",
                website, typ, old_dl, new_dl
            )
            continue

        updates.append((f"{typ}_deadline", f"{typ}_deadline_label", f"{typ}_deadline_previous", new_dl, new_label))
        if old_dl is not None:
            notify_changes.append({"old": old_dl, "new": new_dl,
                                   "label": new_label})
        else:
            logger.info(
                "deadline_verification: %s — first %s found: %s",
                website, f"{typ}_deadline", new_dl
            )

    return updates, notify_changes


def _apply_updates(conf_id: int, updates: list, website: str) -> bool:
    """Persist deadline changes. Returns True on success."""
    conn = None
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        for field, label_field, prev_field, new_val, new_lbl in updates:
            if not {field, label_field, prev_field} <= ALLOWED_FIELDS:
                logger.error(
                    "deadline_verification: rejected unsafe field names for %s",
                    website
                )
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
        return True
    except Exception as e:
        logger.error(
            "deadline_verification: DB update failed for %s: %s",
            website, e
        )
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _process_conference(row, playwright) -> None:
    """Re-extract one conference and apply validated deadline changes."""
    conf_id, title, website = row[0], row[1], row[2]
    old_values = _extract_old_deadlines(row)

    try:
        result = extract(website, playwright)
    except Exception as e:
        logger.error(
            "deadline_verification: extraction error for %s: %s", website, e
        )
        return

    if not result or not result.get("is_conference"):
        logger.warning(
            "deadline_verification: could not re-extract %s", website
        )
        return

    # ── Validation layers ──
    new_values = {}
    stored_values = {}
    for typ in DEADLINE_TYPES:
        new_values[typ] = _parse_date_safe(result.get(f"{typ}_deadline"))
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
        return

    # Layer C: context keyword validation
    context_mismatches = _check_deadline_context(result)

    updates, notify_changes = _diff_deadlines(
        result, old_values, swapped_fields, context_mismatches, website
    )
    if not updates:
        logger.info("deadline_verification: %s — no change", website)
        return

    if not _apply_updates(conf_id, updates, website):
        return

    # Only send notification if there are actual changes (not first discoveries)
    if notify_changes:
        send_deadline_change_notification(title, website, notify_changes)


def verify_deadlines(playwright) -> None:
    """
    Re-extract submission deadlines for all upcoming conferences.
    Runs at most once per day (guarded by daily_tasks table).
    If a deadline changed, updates the DB and
    sends a Telegram notification about the extension/change.
    Only processes conferences with date_start > today.
    Only checks conferences with at least one non-null deadline.
    """
    if not _should_run_verification():
        return

    logger.info("deadline_verification: starting daily deadline re-check")

    rows = _load_conferences_for_verification()
    if rows is None:
        return

    if not rows:
        logger.info("deadline_verification: no upcoming conferences to check")
        db.mark_verification_done()
        return

    logger.info(
        "deadline_verification: checking %d conference(s)", len(rows)
    )

    for row in rows:
        try:
            _process_conference(row, playwright)
        except Exception as e:
            logger.error(
                "deadline_verification: error processing %s: %s", row[2], e
            )
            continue

    db.mark_verification_done()
    logger.info("deadline_verification: complete")
