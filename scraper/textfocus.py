"""Selecting the part of a page that actually contains deadlines.

A conference homepage is mostly navigation, sponsor logos and committee lists.
The important dates table is often 15-30k characters into `body.innerText`,
so the old approach — send the first 8000 characters — silently dropped the
deadlines on exactly the long pages that needed extracting.

`focus_text()` keeps the head of the page (title, scope, host university) and
then adds only the regions that mention a date or a deadline keyword, in page
order, until a character budget is used up. On a short page it is a no-op.
"""

from __future__ import annotations

import re

#: Always keep this much of the head: title, tagline, venue, organiser.
HEAD_CHARS = 2000

#: Total budget handed to the model. Generous because the free tier limits
#: requests per day, not tokens — recall is worth far more than input size.
DEFAULT_BUDGET = 14000

#: Characters of context kept around each interesting line, so a bare date on
#: its own line still arrives with the label that sits above or below it.
CONTEXT_CHARS = 320

_DATE_PATTERNS = re.compile(
    r"(?:19|20)\d{2}-\d{1,2}-\d{1,2}"                                  # 2027-01-15
    r"|\d{1,2}[/.]\d{1,2}[/.](?:19|20)\d{2}"                            # 15/01/2027
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s*(?:19|20)\d{2}"        # January 15, 2027
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
    r"\s*,?\s*(?:19|20)\d{2}",                                          # 15 January 2027
    re.IGNORECASE,
)

_KEYWORDS = re.compile(
    r"deadline|due\s+(?:date|by|on)|last\s+date|closing\s+date|closes?\s+on"
    r"|submission|submit|abstract|full\s+paper|manuscript|camera[-\s]?ready"
    r"|call\s+for\s+paper|cfp|important\s+date|key\s+date|timeline"
    r"|notification|acceptance|registration|extended|extension"
    r"|revised|new\s+deadline|final\s+date",
    re.IGNORECASE,
)


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
    """Rank a span: date mentions count double, keywords single.

    A span with real dates in it is far more valuable than one that merely says
    "submission", so when the budget is tight the dated regions survive.
    """
    chunk = text[span[0]:span[1]]
    return 2 * len(_DATE_PATTERNS.findall(chunk)) + len(_KEYWORDS.findall(chunk))


def focus_text(text: str, budget: int = DEFAULT_BUDGET, head_chars: int = HEAD_CHARS) -> str:
    """Compress page text down to `budget` characters, keeping the deadlines.

    Returns the text unchanged when it already fits. Otherwise returns the head
    followed by the highest-scoring date/deadline regions in page order,
    separated by an ellipsis marker so the model can tell text was elided.
    """
    if not text:
        return ""
    if len(text) <= budget:
        return text

    # A head longer than the whole budget would blow past it.
    head = text[:min(head_chars, budget)]
    remaining = budget - len(head)
    if remaining <= 0:
        return head

    tail_spans = [s for s in _interesting_spans(text) if s[1] > head_chars]
    if not tail_spans:
        # No dates anywhere past the head — a plain prose page. Send a
        # contiguous block rather than nothing.
        return text[:budget]

    # Take the most informative spans first, then restore page order so the
    # model still sees the timeline in sequence.
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
