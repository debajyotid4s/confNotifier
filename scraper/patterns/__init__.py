"""Façade re-exporting the original scraper.patterns public API."""

from .blocklists import (
    HOST_BLOCKLIST,
    INFRA_LABELS,
    JUNK_SEGMENTS,
    NON_HTML_EXTENSIONS,
    STALE_WORDS,
)
from .classify import classify_link
from .host import _host_labels, _label_looks_like_conference
from .hostname import is_conference_hostname
from .positive import (
    CFP_RE,
    EVENT_WORDS,
    EVENT_YEAR_RE,
    KNOWN_ACRONYMS,
    _ACRONYM_YEAR_RE,
    _HOST_LABEL_SHAPES,
    _LOOKALIKE_WORDS,
    _NON_EVENT_WORDS,
)
from .signals import _positive_signal
from .url import _has_junk_segment, is_blocked_host, is_html_url
from .year import YEARS_AHEAD, YEARS_BACK, _YEAR_RE, _year_verdict, year_window, years_in

__all__ = [
    "YEARS_BACK",
    "YEARS_AHEAD",
    "_YEAR_RE",
    "year_window",
    "years_in",
    "_year_verdict",
    "HOST_BLOCKLIST",
    "JUNK_SEGMENTS",
    "NON_HTML_EXTENSIONS",
    "INFRA_LABELS",
    "STALE_WORDS",
    "EVENT_WORDS",
    "KNOWN_ACRONYMS",
    "_HOST_LABEL_SHAPES",
    "_LOOKALIKE_WORDS",
    "_NON_EVENT_WORDS",
    "_ACRONYM_YEAR_RE",
    "CFP_RE",
    "EVENT_YEAR_RE",
    "_host_labels",
    "_label_looks_like_conference",
    "_has_junk_segment",
    "is_html_url",
    "is_blocked_host",
    "classify_link",
    "is_conference_hostname",
    "_positive_signal",
]
