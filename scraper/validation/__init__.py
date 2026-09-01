"""Façade re-exporting the original scraper.validation public API."""

from .checks import (
    _check_deadline_context,
    _check_deadline_swap,
    _context_mismatch_details,
)
from .core import validate_extraction
from .predicates import all_deadlines_past, has_usable_content
from .verdict import Verdict, _parse_date_safe

__all__ = [
    "Verdict",
    "_parse_date_safe",
    "_check_deadline_swap",
    "_check_deadline_context",
    "_context_mismatch_details",
    "all_deadlines_past",
    "has_usable_content",
    "validate_extraction",
]
