"""Positive signal detection."""

import re

from .blocklists import JUNK_SEGMENTS
from .host import _label_looks_like_conference
from .positive import (
    CFP_RE,
    EVENT_WORDS,
    EVENT_YEAR_RE,
    KNOWN_ACRONYMS,
    _ACRONYM_YEAR_RE,
    _LOOKALIKE_WORDS,
    _NON_EVENT_WORDS,
)


def _positive_signal(labels: list[str], path_and_query: str) -> str | None:
    """Return the name of the first positive conference signal found, else None."""
    for label in labels:
        if _label_looks_like_conference(label):
            return "host_label"
    joined = "".join(labels)
    if any(acr in joined for acr in KNOWN_ACRONYMS):
        return "known_acronym"
    if CFP_RE.search(path_and_query):
        return "cfp_wording"
    if EVENT_YEAR_RE.search(path_and_query):
        return "event_year_path"
    if any(acr in path_and_query for acr in KNOWN_ACRONYMS):
        return "known_acronym_path"
    for word, _year in _ACRONYM_YEAR_RE.findall(path_and_query):
        if word in _NON_EVENT_WORDS or word in _LOOKALIKE_WORDS:
            continue
        if word in JUNK_SEGMENTS:
            continue
        return "acronym_year_path"
    # A plain event word in the path counts only when a live year is nearby;
    # the caller checks the year verdict, so surface the weak signal here.
    for word in EVENT_WORDS:
        if re.search(rf"(?:^|[-_/]){re.escape(word)}(?:$|[-_/s])", path_and_query):
            return "event_word_path"
    return None
