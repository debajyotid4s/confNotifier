"""Façade re-exporting the original scraper.schema public API."""

from .constants import (
    DEADLINE_DB_FIELDS,
    DEADLINE_LABELS,
    DEADLINE_TYPES,
    MAX_DESCRIPTION_WORDS,
    SUBMISSION_TYPES,
    _deadline_field,
    deadline_range_checks,
    deadline_select_columns,
)
from .contract import (
    DEADLINE_SCHEMA_PROPS,
    DEADLINE_SCHEMA_REQUIRED,
    EXTRACTION_SCHEMA,
)
from .date_parsing import (
    MAX_YEARS_AHEAD,
    MAX_YEARS_BEHIND,
    _MONTHS,
    _NON_DATES,
    _TEXT_DATE_RE,
    _build_date,
    coerce_date,
    is_plausible_date,
)
from .keywords import (
    FIELD_KEYWORDS,
    POST_SUBMISSION_KEYWORDS,
    validate_deadline_context,
)
from .normalize import normalize_extraction
from .prompt import SYSTEM_PROMPT
from .sanitize import sanitize_dates

__all__ = [
    "DEADLINE_TYPES",
    "SUBMISSION_TYPES",
    "DEADLINE_LABELS",
    "DEADLINE_DB_FIELDS",
    "_deadline_field",
    "deadline_select_columns",
    "deadline_range_checks",
    "FIELD_KEYWORDS",
    "POST_SUBMISSION_KEYWORDS",
    "validate_deadline_context",
    "MAX_YEARS_AHEAD",
    "MAX_YEARS_BEHIND",
    "_NON_DATES",
    "_MONTHS",
    "_TEXT_DATE_RE",
    "coerce_date",
    "_build_date",
    "is_plausible_date",
    "sanitize_dates",
    "DEADLINE_SCHEMA_PROPS",
    "DEADLINE_SCHEMA_REQUIRED",
    "EXTRACTION_SCHEMA",
    "MAX_DESCRIPTION_WORDS",
    "SYSTEM_PROMPT",
    "normalize_extraction",
]
