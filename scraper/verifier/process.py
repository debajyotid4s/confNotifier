import logging

from scraper.schema import DEADLINE_TYPES, coerce_date
from scraper.validation import _check_deadline_context, _check_deadline_swap

from .diff import _diff_deadlines
from .extract import _re_extract
from .persist import _apply_updates
from .queries import _stored_deadlines

logger = logging.getLogger(__name__)


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
    # Late import so patching scraper.notifier works in tests.
    from scraper.notifier import send_deadline_change_notification

    if _apply_updates(conf_id, updates, website) and notify_changes:
        send_deadline_change_notification(title, website, notify_changes)
