"""scraper/extraction/json_repair/fences.py — fence stripping."""

import re

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")  # noqa: F401 — re-exported for repair


def _strip_json_fences(text: str) -> str:
    """Remove ```json fences that the model wraps around structured replies."""
    return _FENCE_RE.sub("", (text or "").strip()).strip()
