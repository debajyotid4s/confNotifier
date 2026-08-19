"""Weekly deadline re-verification.

Re-extracts deadlines for upcoming conferences, updates the DB when a
deadline changed, and sends a Telegram notification about the change.
First-time discoveries save silently (no notification).
"""

import logging
from datetime import date, datetime, timezone
from urllib.parse import urlparse

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

# Only submission deadlines (abstract/full paper) trigger Telegram change
# notifications. Camera ready / registration changes are still saved to the DB
# (via updates) but are not broadcast to users.
NOTIFY_TYPES = {"abstract", "full_paper"}

VERIFY_WINDOW_DAYS = 30
# Interval (hours) between re-verification runs. The main scraper runs 5x/day
# and calls verify_deadlines at the end of each run; this guard lets updates
# (deadline extensions) be caught within hours instead of once per day.
VERIFY_INTERVAL_HOURS = 8
TASK_NAME = "deadline_verification"

# Whitelist of columns writable during verification (SQL injection guard).
# SECURITY: f-string column names are safe because ALLOWED_FIELDS is a static
# set derived from DEADLINE_DB_FIELDS (schema.py) — all values are hardcoded
# strings like "abstract_deadline", not user input. The UPDATE uses parameterized
# values (%s) for all data. If a new deadline type is added, it must appear in
# DEADLINE_DB_FIELDS to be writable here.
ALLOWED_FIELDS = set(DEADLINE_DB_FIELDS)


def _should_run_verification() -> bool:
    """Interval guard. Returns True when verification should run now.

    Verifies at most once per VERIFY_INTERVAL_HOURS (stored as a timestamp
    in daily_tasks; legacy DATE rows are treated as midnight UTC).
    """
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

        if not row or not row[0]:
            return True
        last_run = row[0]
        # NOTE: datetime is a subclass of date — check datetime FIRST, and
        # only treat as a legacy DATE row when it is not a datetime.
        if isinstance(last_run, datetime):
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
        elif isinstance(last_run, date):
            last_run = datetime.combine(last_run, datetime.min.time(), tzinfo=timezone.utc)
        hours_since = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
        if hours_since < VERIFY_INTERVAL_HOURS:
            logger.info(
                "deadline_verification: last ran %.1fh ago (< %dh), skipping",
                hours_since, VERIFY_INTERVAL_HOURS
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
            SELECT id, title, website, raw_source,
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

    Row layout: id, title, website, raw_source, legacy_dl1, legacy_label1,
    legacy_dl2, legacy_label2, then date+label per DEADLINE_TYPES.
    """
    legacy_dates = {0: row[4], 1: row[6]}
    legacy_labels = {0: row[5], 1: row[7]}
    dl_offset = 8

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
    - notify_changes: list of {"old", "new", "label"} — only real changes to
      submission deadlines (NOTIFY_TYPES), not first-time discoveries.
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
            # The stored value may itself be wrong: an earlier extraction may
            # have misplaced a date into this field. If the stored value now
            # matches ANOTHER field's freshly extracted date, it belonged
            # there — accept the correction instead of blocking it.
            misplaced = any(
                other_typ != typ
                and _parse_date_safe(result.get(f"{other_typ}_deadline")) == old_dl
                for other_typ in DEADLINE_TYPES
            )
            if misplaced:
                logger.warning(
                    "deadline_verification: %s — %s moved backward %s → %s but "
                    "stored value matches new %s — stored value was misplaced, accepting",
                    website, typ, old_dl, new_dl,
                    next(
                        (o for o in DEADLINE_TYPES if o != typ
                         and _parse_date_safe(result.get(f"{o}_deadline")) == old_dl),
                        "?"
                    )
                )
            else:
                logger.warning(
                    "deadline_verification: %s — %s moved backward %s → %s, "
                    "likely extraction error, skipping",
                    website, typ, old_dl, new_dl
                )
                continue

        updates.append((f"{typ}_deadline", f"{typ}_deadline_label", f"{typ}_deadline_previous", new_dl, new_label))
        if old_dl is not None and typ in NOTIFY_TYPES:
            notify_changes.append({"old": old_dl, "new": new_dl,
                                   "label": new_label})
        elif old_dl is not None:
            logger.info(
                "deadline_verification: %s — %s changed %s → %s, saved without "
                "notification (non-submission type)",
                website, typ, old_dl, new_dl
            )
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
    """Re-extract one conference and apply validated deadline changes.

    Re-fetches the originally scraped page (raw_source) first — the stored
    `website` is the LLM's guess and may point at a landing page that does
    not show deadlines. Falls back to `website`, then logs loudly when the
    re-extraction is inconclusive so missed updates are never silent.
    """
    conf_id, title, website = row[0], row[1], row[2]
    raw_source = row[3]
    old_values = _extract_old_deadlines(row)

    result = None
    used_url = None
    for candidate_url in dict.fromkeys([raw_source, website]):
        if not candidate_url:
            continue
        if urlparse(candidate_url).scheme not in ("http", "https"):
            logger.debug(
                "deadline_verification: skipping non-URL raw_source %r for %s",
                candidate_url, title
            )
            continue
        try:
            result = extract(
                candidate_url,
                playwright,
                previous_deadlines=old_values,
                wait_until="load",
            )
        except Exception as e:
            logger.error(
                "deadline_verification: extraction error for %s: %s",
                candidate_url, e
            )
            continue
        if result and result.get("is_conference"):
            used_url = candidate_url
            break
        logger.warning(
            "deadline_verification: inconclusive re-extraction at %s — trying next URL",
            candidate_url
        )

    if not result or not result.get("is_conference"):
        logger.warning(
            "deadline_verification: could not re-extract %s (tried raw_source=%s, website=%s) — "
            "deadline changes may be missed; check manually",
            title, raw_source, website
        )
        return

    if used_url and used_url != website:
        logger.info(
            "deadline_verification: re-extracted %s via %s (stored website is %s)",
            title, used_url, website
        )

    # A previously-known conference that now yields zero deadlines is a red
    # flag (page restructured, deadline moved to an image/PDF, fetch issue).
    if any(old_values[t]["date"] for t in DEADLINE_TYPES) and not any(
        result.get(f"{t}_deadline") for t in DEADLINE_TYPES
    ):
        logger.warning(
            "deadline_verification: %s — extraction returned NO deadlines while the DB has %d; "
            "the page may have changed structure — check manually",
            title,
            sum(1 for t in DEADLINE_TYPES if old_values[t]["date"])
        )

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
    Runs at most once every VERIFY_INTERVAL_HOURS (guarded by daily_tasks table).
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
