import logging

from scraper.schema import SUBMISSION_TYPES, validate_deadline_context

logger = logging.getLogger(__name__)


def _check_deadline_swap(new_values: dict, stored_values: dict) -> set:
    """Detect abstract ↔ full_paper having traded places."""
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
                    typ1, new1, typ2, new2,
                )
    return swapped


def _check_deadline_context(conf: dict) -> set:
    """Deadline types whose quoted page text describes something else."""
    mismatches = set()
    for typ in SUBMISSION_TYPES:
        context = conf.get(f"{typ}_deadline_context")
        if not context:
            continue
        valid, mismatched_field = validate_deadline_context(typ, context)
        if not valid:
            mismatches.add(typ)
            logger.warning(
                "deadline_context: %s context (%s) describes %s — probable mis-assignment",
                typ, context.strip()[:60], mismatched_field,
            )
    return mismatches


def _context_mismatch_details(conf: dict) -> dict:
    """Map each mismatched deadline type to the field its text describes."""
    details = {}
    for typ in SUBMISSION_TYPES:
        context = conf.get(f"{typ}_deadline_context")
        if not context:
            continue
        valid, mismatched_field = validate_deadline_context(typ, context)
        if not valid:
            details[typ] = mismatched_field
    return details
