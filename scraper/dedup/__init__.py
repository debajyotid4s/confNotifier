"""Façade re-exporting the original scraper.dedup public API."""

from .edition import edition_key, edition_year
from .index import ConferenceIndex
from .title import (
    _ACRONYM_RE,
    _ROMAN_RE,
    _TITLE_STOPWORDS,
    acronym_from_title,
    title_key,
)
from .url import (
    _INDEX_FILES,
    _JUNK_QUERY_PREFIXES,
    _REDUNDANT_TAIL,
    _clean_query,
    canonical_url,
    same_url,
)

__all__ = [
    "_INDEX_FILES",
    "_REDUNDANT_TAIL",
    "_JUNK_QUERY_PREFIXES",
    "canonical_url",
    "_clean_query",
    "same_url",
    "_TITLE_STOPWORDS",
    "_ROMAN_RE",
    "_ACRONYM_RE",
    "acronym_from_title",
    "title_key",
    "edition_year",
    "edition_key",
    "ConferenceIndex",
]
