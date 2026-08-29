"""scraper/extraction/json_repair.py — salvage near-valid Gemini JSON."""

import json
import re


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _strip_json_fences(text: str) -> str:
    """Remove ```json fences that the model wraps around structured replies."""
    return _FENCE_RE.sub("", (text or "").strip()).strip()


def _close_truncated(text: str) -> str | None:
    """Close a JSON object that was cut off mid-way by the token limit."""
    stack: list[str] = []
    in_string = False
    escaped = False
    cut_at: int | None = None
    cut_stack: list[str] = []

    for i, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            if not stack:
                return text[:i + 1]
            cut_at, cut_stack = i + 1, list(stack)
        elif ch == "," and len(stack) == 1:
            cut_at, cut_stack = i, list(stack)
    if cut_at is None:
        return None
    body = text[:cut_at].rstrip().rstrip(",")
    if not body:
        return None
    return body + "".join(reversed(cut_stack))


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
