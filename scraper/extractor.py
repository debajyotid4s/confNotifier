"""scraper/extractor.py — thin facade.

All logic lives in scraper/extraction/* (<150 lines each). This shim keeps
`from scraper.extractor import extract` and `from scraper.extractor import _call_gemini`
working with zero caller changes.
"""

from scraper.extraction.client import _call_gemini, call_gemini, daily_quota_exhausted, total_requests_today  # noqa: F401
from scraper.extraction.core import extract, extract_conferences  # noqa: F401
from scraper.extraction.json_repair import repair_json  # noqa: F401
from scraper.extraction.rate_limiter import GoogleRateLimiter  # noqa: F401

__all__ = ["GoogleRateLimiter", "repair_json", "call_gemini", "_call_gemini", "daily_quota_exhausted", "total_requests_today", "extract", "extract_conferences"]
