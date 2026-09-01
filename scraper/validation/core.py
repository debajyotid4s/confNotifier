from datetime import date

from scraper.schema import SUBMISSION_TYPES, coerce_date

from .checks import _check_deadline_swap, _context_mismatch_details
from .predicates import all_deadlines_past
from .verdict import Verdict


def validate_extraction(conf: dict, stored_deadlines: dict | None = None,
                        now: date | None = None) -> Verdict:
    """Run every check against one extraction and return a single verdict."""
    mismatches = _context_mismatch_details(conf)
    if mismatches:
        described = ", ".join(
            f"{typ}→{actual}" for typ, actual in sorted(mismatches.items())
        )
        return Verdict.reject(
            f"context mismatch ({described})",
            fields=mismatches.keys(),
            permanent=True,
        )
    if all_deadlines_past(conf, now):
        return Verdict.reject(
            "all extracted deadlines are in the past", permanent=True
        )
    if stored_deadlines:
        new_values = {
            t: coerce_date(conf.get(f"{t}_deadline")) for t in SUBMISSION_TYPES
        }
        stored_values = {
            t: coerce_date(stored_deadlines.get(t)) for t in SUBMISSION_TYPES
        }
        if any(new_values.values()) and any(stored_values.values()):
            swapped = _check_deadline_swap(new_values, stored_values)
            if swapped:
                return Verdict.reject(
                    f"deadline swap detected for {sorted(swapped)}",
                    fields=swapped,
                )
    return Verdict.valid()
