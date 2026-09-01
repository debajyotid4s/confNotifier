"""Façade re-exporting the original scraper.browser public API."""

from .constants import MAX_PAGE_TEXT_CHARS, MIN_PAGE_TEXT_CHARS, USER_AGENTS
from .manager import PlaywrightManager

__all__ = [
    "MAX_PAGE_TEXT_CHARS",
    "MIN_PAGE_TEXT_CHARS",
    "PlaywrightManager",
    "USER_AGENTS",
]
