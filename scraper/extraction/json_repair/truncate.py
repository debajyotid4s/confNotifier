"""scraper/extraction/json_repair/truncate.py — close truncated JSON."""


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
