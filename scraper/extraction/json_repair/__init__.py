"""scraper/extraction/json_repair — package facade."""

from scraper.extraction.json_repair.fences import _FENCE_RE, _TRAILING_COMMA_RE, _strip_json_fences  # noqa: F401
from scraper.extraction.json_repair.repair import repair_json  # noqa: F401
from scraper.extraction.json_repair.truncate import _close_truncated  # noqa: F401

__all__ = ["_FENCE_RE", "_TRAILING_COMMA_RE", "_strip_json_fences", "_close_truncated", "repair_json"]
