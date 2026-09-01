from .constants import DEFAULT_BUDGET, HEAD_CHARS
from .spans import _interesting_spans, _score


def focus_text(text: str, budget: int = DEFAULT_BUDGET,
               head_chars: int = HEAD_CHARS) -> str:
    """Compress page text down to `budget` characters, keeping the deadlines."""
    if not text:
        return ""
    if len(text) <= budget:
        return text
    head = text[:min(head_chars, budget)]
    remaining = budget - len(head)
    if remaining <= 0:
        return head
    tail_spans = [s for s in _interesting_spans(text) if s[1] > head_chars]
    if not tail_spans:
        return text[:budget]
    chosen: list[tuple[int, int]] = []
    used = 0
    for span in sorted(tail_spans, key=lambda s: _score(text, s), reverse=True):
        start = max(span[0], head_chars)
        length = span[1] - start
        if length <= 0:
            continue
        if used + length > remaining:
            continue
        chosen.append((start, span[1]))
        used += length
    if not chosen:
        return text[:budget]
    chosen.sort()
    parts = [head]
    previous_end = head_chars
    for start, end in chosen:
        if start > previous_end:
            parts.append("\n[...]\n")
        parts.append(text[start:end])
        previous_end = end
    return "".join(parts)[:budget]
