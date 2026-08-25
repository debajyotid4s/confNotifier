"""Deadline re-verification.

Conference organisers extend deadlines constantly and rarely announce it
anywhere but the website. This module re-extracts the deadlines for every
upcoming conference, updates the record when a date moved, and posts the change
to Telegram with the old date struck through.

Guards that matter:
  - interval-limited (VERIFY_INTERVAL_HOURS) so five daily scraper runs do not
    re-extract everything five times
  - a deadline moving *backwards* is treated as an extraction error and skipped,
    unless the stored value turns out to belong to the other deadline field
  - a first-time discovery (NULL → date) is saved silently; it is not a "change"
  - `raw_source` is re-fetched before `website`, because `website` is the model's
    guess and often points at a landing page with no dates on it
"""

import logging
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from scraper import db
from scraper.extractor import extract
from scraper.notifier import send_deadline_change_notification
from scraper.schema import (
    DEADLINE_DB_FIELDS,
    DEADLINE_LABELS,
    DEADLINE_TYPES,
    SUBMISSION_TYPES,
    coerce_date,
    deadline_range_checks,
    deadline_select_columns,
)
from scraper.validation import _check_deadline_context, _check_deadline_swap

logger = logging.getLogger(__name__)

#: Only submission deadlines are broadcast; the rest are stored context.
NOTIFY_TYPES = frozenset(SUBMISSION_TYPES)

#: Window around today that counts as "upcoming". Symmetric so a deadline that
#: just passed is still re-checked — that is exactly when extensions appear.
VERIFY_WINDOW_DAYS = 30
VERIFY_INTERVAL_HOURS = 8
TASK_NAME = "deadline_verification"

#: Columns verification is allowed to write. The UPDATE interpolates column names
#: (values are always parameterised), so the set is checked before each statement.
#: Every member comes from schema.DEADLINE_DB_FIELDS — hardcoded, never input.
ALLOWED_FIELDS = frozenset(DEADLINE_DB_FIELDS)


def _should_run_verification() -> bool:
    """True when the last run is older than VERIFY_INTERVAL_HOURS.

    Errors resolve to True: missing a verification is worse than doing one twice.
    """
    last_run = db.get_task_last_run(TASK_NAME)
    if not last_run:
        return True

    # datetime subclasses date, so check datetime first; legacy DATE rows are
    # treated as midnight UTC.
    if isinstance(last_run, datetime):
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
    elif isinstance(last_run, date):
        last_run = datetime.combine(last_run, datetime.min.time(), tzinfo=timezone.utc)
    else:
        return True

    hours_since = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
    if hours_since < VERIFY_INTERVAL_HOURS:
        logger.info("deadline_verification: last ran %.1fh ago (< %dh), skipping",
                    hours_since, VERIFY_INTERVAL_HOURS)
        return False
    return True


def _load_conferences_for_verification() -> list | None:
    """Upcoming conferences with a deadline inside the verify window.

    Returns None on a DB error so the caller can skip the run instead of
    stamping it as done.
    """
    select_dl = ", ".join(deadline_select_columns())
    window = " OR ".join(deadline_range_checks(VERIFY_WINDOW_DAYS, past_days=VERIFY_WINDOW_DAYS))
    try:
        with db.db_cursor() as cur:
            cur.execute(f"""
                SELECT id, title, website, raw_source, {select_dl}
                FROM conferences
                WHERE date_start > CURRENT_DATE
                  AND ({window})
                ORDER BY date_start ASC
            """)
            return cur.fetchall()
    except Exception as e:
        logger.error("deadline_verification: failed to load conferences: %s", e)
        return None


#: Index of the first deadline column in the verification row.
_DL_OFFSET = 4


def _stored_deadlines(row) -> dict:
    """Map a verification row to {type: {date, label}}."""
    return {
        typ: {
            "date": row[_DL_OFFSET + i * 2],
            "label": row[_DL_OFFSET + i * 2 + 1],
        }
        for i, typ in enumerate(DEADLINE_TYPES)
    }


def _accept_backward_move(typ: str, old_dl, result: dict) -> bool:
    """Decide whether a deadline moving earlier is a correction or an error.

    A deadline should never move backwards. But an earlier extraction may have
    put a date in the wrong field; if the stored value now matches another
    field's freshly extracted date, it belonged there, and this field's new
    (earlier) value is the correction. Accept only in that case.
    """
    for other in DEADLINE_TYPES:
        if other == typ:
            continue
        if coerce_date(result.get(f"{other}_deadline")) == old_dl:
            logger.warning(
                "deadline_verification: %s moved backward but stored value matches "
                "new %s — stored value was misplaced, accepting correction", typ, other,
            )
            return True
    return False


def _diff_deadlines(result: dict, stored: dict, swapped: set,
                    mismatched: set, website: str):
    """Compare a fresh extraction with stored values.

    Returns (updates, notify_changes):
      updates        — (field, label_field, previous_field, new_date, new_label)
      notify_changes — {"old", "new", "label"} for real changes only
    """
    updates, notify_changes = [], []

    for typ in DEADLINE_TYPES:
        if typ in swapped:
            logger.warning("deadline_verification: %s — %s swapped, skipping", website, typ)
            continue
        if typ in mismatched:
            logger.warning("deadline_verification: %s — %s context mismatch, skipping",
                           website, typ)
            continue

        new_dl = coerce_date(result.get(f"{typ}_deadline"))
        if not new_dl:
            continue

        old_dl = stored[typ]["date"]
        if new_dl == old_dl:
            continue

        if old_dl is not None and new_dl < old_dl and not _accept_backward_move(typ, old_dl, result):
            logger.warning("deadline_verification: %s — %s moved backward %s → %s, "
                           "likely extraction error, skipping", website, typ, old_dl, new_dl)
            continue

        new_label = result.get(f"{typ}_deadline_label") or DEADLINE_LABELS.get(typ, typ)
        updates.append((f"{typ}_deadline", f"{typ}_deadline_label",
                        f"{typ}_deadline_previous", new_dl, new_label))

        if old_dl is None:
            logger.info("deadline_verification: %s — first %s deadline found: %s",
                        website, typ, new_dl)
        elif typ in NOTIFY_TYPES:
            notify_changes.append({"old": old_dl, "new": new_dl, "label": new_label})

    return updates, notify_changes


def _apply_updates(conf_id: int, updates: list, website: str) -> bool:
    """Write deadline changes to both the wide columns and the child table."""
    try:
        with db.db_cursor(commit=True) as cur:
            for field, label_field, prev_field, new_val, new_lbl in updates:
                if not {field, label_field, prev_field} <= ALLOWED_FIELDS:
                    logger.error("deadline_verification: rejected unsafe field names for %s",
                                 website)
                    continue
                cur.execute(f"""
                    UPDATE conferences
                    SET {field} = %s,
                        {label_field} = %s,
                        {prev_field} = CASE
                            WHEN {field} IS NOT NULL AND {field} != %s AND {prev_field} IS NULL
                            THEN {field} ELSE {prev_field}
                        END,
                        deadline_last_verified = NOW()
                    WHERE id = %s
                """, (new_val, new_lbl, new_val, conf_id))

                # Keep the indexed child table — which the API reads — in step.
                typ = field.removesuffix("_deadline")
                cur.execute("""
                    INSERT INTO conference_deadlines
                        (conference_id, type, deadline, deadline_label)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (conference_id, type) DO UPDATE SET
                        deadline_previous = CASE
                            WHEN conference_deadlines.deadline IS NOT NULL
                             AND conference_deadlines.deadline != EXCLUDED.deadline
                            THEN conference_deadlines.deadline
                            ELSE conference_deadlines.deadline_previous
                        END,
                        deadline = EXCLUDED.deadline,
                        deadline_label = EXCLUDED.deadline_label
                """, (conf_id, typ, new_val, new_lbl))

        logger.info("deadline_verification: updated %s — %d field(s) saved",
                    website, len(updates))
        return True
    except Exception as e:
        logger.error("deadline_verification: DB update failed for %s: %s", website, e)
        return False


def _re_extract(row, playwright) -> tuple[dict | None, str | None]:
    """Re-extract a conference, trying raw_source before website.

    `website` is what the model reported and is often a landing page without
    dates; `raw_source` is the page we actually scraped.
    """
    title, website, raw_source = row[1], row[2], row[3]
    stored = _stored_deadlines(row)

    for candidate_url in dict.fromkeys([raw_source, website]):
        if not candidate_url or urlparse(candidate_url).scheme not in ("http", "https"):
            continue
        try:
            result = extract(candidate_url, playwright, previous_deadlines=stored,
                             wait_until="load")
        except Exception as e:
            logger.error("deadline_verification: extraction error for %s: %s", candidate_url, e)
            continue
        if result and result.get("is_conference"):
            return result, candidate_url
        logger.warning("deadline_verification: inconclusive re-extraction at %s", candidate_url)

    logger.warning(
        "deadline_verification: could not re-extract %s (raw_source=%s, website=%s) — "
        "deadline changes may be missed", title, raw_source, website,
    )
    return None, None


def _process_conference(row, playwright) -> None:
    """Re-extract one conference and apply any validated deadline change."""
    conf_id, title, website = row[0], row[1], row[2]
    stored = _stored_deadlines(row)

    result, used_url = _re_extract(row, playwright)
    if not result:
        return
    if used_url != website:
        logger.info("deadline_verification: re-extracted %s via %s (stored website %s)",
                    title, used_url, website)

    had_deadlines = sum(1 for t in DEADLINE_TYPES if stored[t]["date"])
    if had_deadlines and not any(result.get(f"{t}_deadline") for t in DEADLINE_TYPES):
        # Loud, because silence here means a quietly broken conference record.
        logger.warning(
            "deadline_verification: %s — extraction found NO deadlines while the DB has %d; "
            "the page may have been restructured — check manually", title, had_deadlines,
        )

    new_values = {t: coerce_date(result.get(f"{t}_deadline")) for t in DEADLINE_TYPES}
    stored_values = {t: stored[t]["date"] for t in DEADLINE_TYPES}

    swapped = _check_deadline_swap(new_values, stored_values)
    mismatched = _check_deadline_context(result)

    updates, notify_changes = _diff_deadlines(result, stored, swapped, mismatched, website)
    if not updates:
        logger.info("deadline_verification: %s — no change", website)
        return

    if _apply_updates(conf_id, updates, website) and notify_changes:
        send_deadline_change_notification(title, website, notify_changes)


def verify_deadlines(playwright) -> None:
    """Re-extract deadlines for upcoming conferences and announce any change."""
    if not _should_run_verification():
        return

    logger.info("deadline_verification: starting deadline re-check")

    rows = _load_conferences_for_verification()
    if rows is None:
        return
    if not rows:
        logger.info("deadline_verification: no upcoming conferences to check")
        db.mark_verification_done()
        return

    logger.info("deadline_verification: checking %d conference(s)", len(rows))
    for row in rows:
        try:
            _process_conference(row, playwright)
        except Exception as e:
            logger.error("deadline_verification: error processing %s: %s", row[2], e)

    db.mark_verification_done()
    logger.info("deadline_verification: complete")
