import logging
from datetime import date

from scraper.schema import DEADLINE_TYPES, validate_deadline_context

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
    """Layer A: cross-field swap detection.

    Flags a pair of fields only for a TWO-WAY swap: the new value of field A
    equals the stored value of field B, AND the new value of field B equals
    the stored value of field A. A genuine Gemini field swap is two-way by
    definition. One-way date matches are usually coincidence (deadlines
    repeat/align) or evidence that a stored value was itself misplaced — they
    are not swaps and must not block updates.

    Returns set of field types involved in a two-way swap.
    """
    swapped = set()
    for typ1 in DEADLINE_TYPES:
        new1 = new_values.get(typ1)
        if new1 is None:
            continue
        for typ2 in DEADLINE_TYPES:
            if typ2 <= typ1:  # each pair considered once
                continue
            new2 = new_values.get(typ2)
            if new2 is None:
                continue
            if new1 == stored_values.get(typ2) and new2 == stored_values.get(typ1):
                swapped.update((typ1, typ2))
                logger.warning(
                    "deadline_swap: two-way swap between %s (%s) and %s (%s)",
                    typ1, new1, typ2, new2
                )
    return swapped


def _check_chronological_order(new_values: dict, conference_start: date | None) -> bool:
    """Layer B: enforce abstract ≤ full_paper ≤ camera_ready ≤ registration ≤ conference_start.

    null values are skipped (no constraint). Returns True if ordering is valid.
    """
    ordered_types = ["abstract", "full_paper", "camera_ready", "registration"]
    dates = [new_values.get(t) for t in ordered_types]
    dates.append(conference_start)
    labels = list(ordered_types) + ["conference_start"]

    for i in range(len(dates) - 1):
        if dates[i] is not None and dates[i + 1] is not None:
            if dates[i] > dates[i + 1]:
                logger.warning(
                    "chronological_order: %s (%s) > %s (%s) — violates constraint",
                    labels[i], dates[i], labels[i + 1], dates[i + 1]
                )
                return False
    return True


def _check_deadline_context(conf: dict) -> set:
    """Layer C: validate deadline context against FIELD_KEYWORDS.

    Returns set of field types whose context text mismatches (e.g. context says
    'camera ready' but landed in 'abstract').
    """
    mismatches = set()
    for typ in DEADLINE_TYPES:
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
