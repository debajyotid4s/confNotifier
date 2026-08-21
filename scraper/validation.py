import logging
from datetime import date

from scraper.schema import SUBMISSION_TYPES, validate_deadline_context

logger = logging.getLogger(__name__)


def _parse_date_safe(date_str):
    """Parse a YYYY-MM-DD string to date, return None on failure."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(str(date_str))
    except (ValueError, TypeError):
        return None


def _check_deadline_swap(new_values: dict, stored_values: dict) -> set:
    """Layer A: submission swap detection (intentional, minimal).

    Only submission deadlines matter — other types are stored but not used.
    Flags a TWO-WAY swap between abstract ↔ full_paper: the new value of one
    equals the stored value of the other and vice-versa. One-way matches are
    ignored (coincidence or previously misplaced value).
    Returns set of field types involved in the swap.
    """
    swapped = set()
    for i, typ1 in enumerate(SUBMISSION_TYPES):
        new1 = new_values.get(typ1)
        if new1 is None:
            continue
        for typ2 in SUBMISSION_TYPES[i + 1:]:
            new2 = new_values.get(typ2)
            if new2 is None or new1 == new2:
                continue
            if new1 == stored_values.get(typ2) and new2 == stored_values.get(typ1):
                swapped.update((typ1, typ2))
                logger.warning(
                    "deadline_swap: two-way swap between %s (%s) and %s (%s)",
                    typ1, new1, typ2, new2
                )
    return swapped


def _check_deadline_context(conf: dict) -> set:
    """Layer C: context check for submission deadlines only.

    Other types are stored but not used — no need to validate them.
    Returns set of mismatched submission types.
    """
    mismatches = set()
    for typ in SUBMISSION_TYPES:
        context = conf.get(f"{typ}_deadline_context")
        if not context:
            continue
        valid, mismatched_field = validate_deadline_context(typ, context)
        if not valid:
            mismatches.add(typ)
            logger.warning(
                "deadline_context: %s context (%s) matches %s keywords — probable swap",
                typ, context.strip()[:60], mismatched_field
            )
    return mismatches
