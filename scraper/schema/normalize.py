"""Flatten nested deadline objects and sanitise values."""

import logging
from datetime import date

from .constants import DEADLINE_LABELS, DEADLINE_TYPES, MAX_DESCRIPTION_WORDS
from .sanitize import sanitize_dates

logger = logging.getLogger(__name__)


def normalize_extraction(result: dict, now: date | None = None) -> dict:
    """Flatten nested deadline objects and sanitise every value.

    Produces the flat shape the rest of the pipeline expects:
      {typ}_deadline          ISO date string or None
      {typ}_deadline_label    fixed human label
      {typ}_deadline_context  page text that justified the date

    Also clamps the description to MAX_DESCRIPTION_WORDS and records any
    dropped dates under "sanitize_notes" for the caller to log.
    """
    normalized = dict(result)
    for typ in DEADLINE_TYPES:
        field_name = f"{typ}_deadline"
        deadline_obj = result.get(field_name)
        if isinstance(deadline_obj, dict):
            normalized[field_name] = deadline_obj.get("date")
            normalized[f"{typ}_deadline_context"] = deadline_obj.get("context")
        else:
            normalized[f"{typ}_deadline_context"] = None
        normalized[f"{typ}_deadline_label"] = DEADLINE_LABELS.get(typ, typ)
    normalized, notes = sanitize_dates(normalized, now)
    if notes:
        for note in notes:
            logger.warning("sanitize: %s", note)
    normalized["sanitize_notes"] = notes
    description = normalized.get("description")
    if isinstance(description, str):
        words = description.split()
        if len(words) > MAX_DESCRIPTION_WORDS:
            logger.warning("overview_wordcount_violation: %d words (max %d), truncating",
                           len(words), MAX_DESCRIPTION_WORDS)
            normalized["description"] = " ".join(words[:MAX_DESCRIPTION_WORDS])
    elif description is not None:
        normalized["description"] = None
    return normalized
