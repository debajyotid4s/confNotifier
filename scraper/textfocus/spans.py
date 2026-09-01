from .constants import CONTEXT_CHARS
from .patterns import _DATE_PATTERNS, _KEYWORDS


def _interesting_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges worth sending, widened by CONTEXT_CHARS and merged."""
    hits: list[int] = []
    for pattern in (_DATE_PATTERNS, _KEYWORDS):
        hits.extend(m.start() for m in pattern.finditer(text))
    if not hits:
        return []
    spans = sorted(
        (max(0, h - CONTEXT_CHARS), min(len(text), h + CONTEXT_CHARS))
        for h in hits
    )
    merged = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _score(text: str, span: tuple[int, int]) -> int:
    """Rank a span: date mentions count double, keywords single."""
    chunk = text[span[0]:span[1]]
    return 2 * len(_DATE_PATTERNS.findall(chunk)) + len(_KEYWORDS.findall(chunk))
