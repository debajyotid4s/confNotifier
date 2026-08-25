"""Validation of a fresh extraction before it is trusted.

The important distinction here is **permanent vs transient**.

A context mismatch ("the abstract deadline is labelled 'camera ready' on the
page") is a property of the page: re-fetching it produces the same answer. The
old code marked those URLs `failed_transient`, so each one was re-extracted three
more times with widening backoff — up to 9 wasted Gemini calls against a daily
budget of 60. `Verdict.permanent` now routes them straight to a terminal status.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from scraper.schema import SUBMISSION_TYPES, coerce_date, validate_deadline_context

logger = logging.getLogger(__name__)


def _parse_date_safe(date_str):
    """Parse a date-ish value, returning None instead of raising."""
    return coerce_date(date_str)


@dataclass
class Verdict:
    """Outcome of validating one extraction.

    `ok`        — nothing wrong, save it
    `permanent` — the page itself is the problem; do not retry
    `reason`    — human-readable explanation for the log
    `fields`    — which deadline types are implicated
    """

    ok: bool = True
    permanent: bool = False
    reason: str = ""
    fields: set = field(default_factory=set)

    def __bool__(self) -> bool:
        return self.ok

    @classmethod
    def valid(cls) -> "Verdict":
        return cls()

    @classmethod
    def reject(cls, reason: str, fields=None, permanent: bool = False) -> "Verdict":
        return cls(ok=False, permanent=permanent, reason=reason, fields=set(fields or ()))


def _check_deadline_swap(new_values: dict, stored_values: dict) -> set:
    """Detect abstract ↔ full_paper having traded places.

    Only a *two-way* swap counts: the new value of each field equals the stored
    value of the other. A one-way match is ordinary coincidence (or a stored
    value that was already wrong) and must not block a legitimate update.
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
                logger.warning("deadline_swap: two-way swap between %s (%s) and %s (%s)",
                               typ1, new1, typ2, new2)
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
    """Map each mismatched deadline type to the field its text actually describes."""
    details = {}
    for typ in SUBMISSION_TYPES:
        context = conf.get(f"{typ}_deadline_context")
        if not context:
            continue
        valid, mismatched_field = validate_deadline_context(typ, context)
        if not valid:
            details[typ] = mismatched_field
    return details


def has_usable_content(conf: dict) -> bool:
    """True when an extraction carries at least one fact worth storing.

    A record with no deadline and no conference date is a TBA placeholder. It is
    still saved (so the edition is tracked and re-checked) but it must not be
    treated as a successful extraction that satisfies the caller.
    """
    return bool(
        conf.get("date_start")
        or conf.get("date_end")
        or any(conf.get(f"{typ}_deadline") for typ in SUBMISSION_TYPES)
    )


def all_deadlines_past(conf: dict, now: date | None = None) -> bool:
    """True when every deadline present has already passed.

    Catches the stale-edition case that a `date_start` check misses: a page with
    no conference dates but submission deadlines from two years ago.
    """
    today = now or date.today()
    deadlines = [
        coerce_date(conf.get(f"{typ}_deadline"))
        for typ in SUBMISSION_TYPES
    ]
    present = [d for d in deadlines if d is not None]
    return bool(present) and all(d < today for d in present)


def validate_extraction(conf: dict, stored_deadlines: dict | None = None,
                        now: date | None = None) -> Verdict:
    """Run every check against one extraction and return a single verdict.

    `stored_deadlines` is what the database already holds for this conference
    (ISO strings keyed by deadline type); pass None when the conference is new.
    """
    mismatches = _context_mismatch_details(conf)
    if mismatches:
        # The page's own wording contradicts the assignment. Re-asking the model
        # about the same text cannot change this, so do not spend retries on it.
        described = ", ".join(f"{typ}→{actual}" for typ, actual in sorted(mismatches.items()))
        return Verdict.reject(
            f"context mismatch ({described})",
            fields=mismatches.keys(),
            permanent=True,
        )

    if all_deadlines_past(conf, now):
        return Verdict.reject("all extracted deadlines are in the past", permanent=True)

    if stored_deadlines:
        new_values = {t: coerce_date(conf.get(f"{t}_deadline")) for t in SUBMISSION_TYPES}
        stored_values = {t: coerce_date(stored_deadlines.get(t)) for t in SUBMISSION_TYPES}
        if any(new_values.values()) and any(stored_values.values()):
            swapped = _check_deadline_swap(new_values, stored_values)
            if swapped:
                # A swap against stored values is also deterministic for this
                # page, but the stored value may itself be the wrong one — keep
                # it retryable so a later page edit can correct the record.
                return Verdict.reject(f"deadline swap detected for {sorted(swapped)}",
                                      fields=swapped)

    return Verdict.valid()
