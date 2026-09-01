"""scraper/extraction/json_repair/repair.py — best-effort JSON repair."""

import json

from scraper.extraction.json_repair.fences import _TRAILING_COMMA_RE, _strip_json_fences
from scraper.extraction.json_repair.truncate import _close_truncated


def repair_json(raw: str) -> dict | None:
    """Best-effort parse of a model reply that is not quite valid JSON."""
    if not raw or not raw.strip():
        return None
    candidates: list[str] = []

    def add(value: str | None):
        if value and value.strip() and value not in candidates:
            candidates.append(value.strip())

    add(raw)
    stripped = _strip_json_fences(raw)
    add(stripped)
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        add(stripped[start:end + 1])
    for base in list(candidates):
        add(_TRAILING_COMMA_RE.sub(r"\1", base))
    if start != -1:
        add(_close_truncated(stripped[start:]))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
