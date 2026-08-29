"""scraper/extraction — package facade."""

from scraper.extraction.client import (  # noqa: F401
    DEFAULT_MAX_TOKENS,
    MAX_ATTEMPTS_PER_KEY,
    MODEL,
    _is_transient,
    call_gemini,
    daily_quota_exhausted,
    total_requests_today,
)
from scraper.extraction.client import call_gemini as _call_gemini  # noqa: F401 — legacy alias for change_detector
from scraper.extraction.core import MAX_TEXT_CHARS, MIN_PAGE_TEXT_CHARS, extract, extract_conferences  # noqa: F401
from scraper.extraction.json_repair import repair_json  # noqa: F401
from scraper.extraction.rate_limiter import GoogleRateLimiter  # noqa: F401

__all__ = ["GoogleRateLimiter", "repair_json", "call_gemini", "_call_gemini", "daily_quota_exhausted", "total_requests_today", "extract", "extract_conferences"]
