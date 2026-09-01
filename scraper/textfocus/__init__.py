"""Façade re-exporting the original scraper.textfocus public API."""

from .constants import CONTEXT_CHARS, DEFAULT_BUDGET, HEAD_CHARS
from .focus import focus_text
from .patterns import _DATE_PATTERNS, _KEYWORDS
from .spans import _interesting_spans, _score

__all__ = [
    "CONTEXT_CHARS",
    "DEFAULT_BUDGET",
    "HEAD_CHARS",
    "_DATE_PATTERNS",
    "_KEYWORDS",
    "_interesting_spans",
    "_score",
    "focus_text",
]
