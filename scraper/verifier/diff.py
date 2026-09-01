import logging

from scraper.schema import DEADLINE_LABELS, DEADLINE_TYPES, coerce_date

from .constants import NOTIFY_TYPES

logger = logging.getLogger(__name__)


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
