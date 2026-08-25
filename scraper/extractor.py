"""Gemini extraction: fetch a page, ask for structured conference data.

Three things make this reliable enough to run unattended on a free tier:

1. **Key rotation with per-key budgets.** Three API keys, each with its own
   5 RPM / 20 RPD limiter. A 429 on one key rotates to the next rather than
   failing the candidate.

2. **JSON repair.** Gemini occasionally returns fence-wrapped, trailing-comma or
   truncated JSON. Previously any of those raised `JSONDecodeError` and the call
   was retried up to three times per key — nine wasted requests out of a daily
   budget of sixty, for a reply that was already 99% parseable.
   `repair_json()` salvages it instead.

3. **Focused input.** `textfocus.focus_text` picks the regions of the page that
   actually mention dates, instead of blindly sending the first 8000 characters.
"""

import json
import logging
import os
import re
import threading
import time
from collections import deque

from openai import OpenAI

from scraper.browser import PlaywrightManager
from scraper.schema import (
    DEADLINE_LABELS,
    DEADLINE_TYPES,
    EXTRACTION_SCHEMA,
    SYSTEM_PROMPT,
    normalize_extraction,
)
from scraper.textfocus import focus_text

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
MAX_TEXT_CHARS = 14000
MIN_PAGE_TEXT_CHARS = 100
DEFAULT_MAX_TOKENS = 4096
MAX_ATTEMPTS_PER_KEY = 3


class GoogleRateLimiter:
    """Google AI Studio free-tier budget for one API key.

    5 requests per rolling 60s window, 20 per calendar day. `acquire()` blocks
    for the RPM window but raises once the daily budget is gone, so the caller
    can rotate keys instead of sleeping for hours.
    """

    RPM_LIMIT = 5
    RPD_LIMIT = 20
    WINDOW_SECONDS = 60

    def __init__(self):
        self._lock = threading.Lock()
        self._request_timestamps = deque()
        self._daily_count = 0
        self._day_start = time.strftime("%Y-%m-%d")

    def _reset_daily_if_needed(self):
        today = time.strftime("%Y-%m-%d")
        if today != self._day_start:
            self._daily_count = 0
            self._day_start = today

    @property
    def daily_count(self) -> int:
        with self._lock:
            self._reset_daily_if_needed()
            return self._daily_count

    def daily_quota_exhausted(self) -> bool:
        with self._lock:
            self._reset_daily_if_needed()
            return self._daily_count >= self.RPD_LIMIT

    def acquire(self):
        """Reserve a request slot, blocking for the RPM window if needed.

        Raises RuntimeError when the daily budget is spent.
        """
        while True:
            with self._lock:
                self._reset_daily_if_needed()

                if self._daily_count >= self.RPD_LIMIT:
                    raise RuntimeError(
                        f"Daily quota exhausted: {self._daily_count}/{self.RPD_LIMIT} "
                        f"requests used today"
                    )

                if self._daily_count >= int(self.RPD_LIMIT * 0.8):
                    logger.warning("Rate limiter: daily quota at %d/%d — approaching limit",
                                   self._daily_count, self.RPD_LIMIT)

                now = time.time()
                cutoff = now - self.WINDOW_SECONDS
                while self._request_timestamps and self._request_timestamps[0] < cutoff:
                    self._request_timestamps.popleft()

                if len(self._request_timestamps) < self.RPM_LIMIT:
                    self._request_timestamps.append(now)
                    self._daily_count += 1
                    return

                wait_seconds = (self._request_timestamps[0] + self.WINDOW_SECONDS) - now + 0.5

            logger.info("Rate limiter: at %d RPM, waiting %.1fs for a slot (daily %d/%d)",
                        self.RPM_LIMIT, wait_seconds, self._daily_count, self.RPD_LIMIT)
            time.sleep(max(wait_seconds, 0.5))

    def release_last(self):
        """Hand back the slot just taken — for failures that were not the model's fault."""
        with self._lock:
            if self._request_timestamps:
                self._request_timestamps.pop()
            if self._daily_count > 0:
                self._daily_count -= 1


# ── JSON recovery ─────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _strip_json_fences(text: str) -> str:
    """Remove ```json fences that the model wraps around structured replies."""
    return _FENCE_RE.sub("", (text or "").strip()).strip()


def _close_truncated(text: str) -> str | None:
    """Close a JSON object that was cut off mid-way by the token limit.

    Walks the text tracking string state and bracket depth, remembering the last
    position where a complete key/value pair ended *together with the bracket
    depth at that position* — truncating back to an earlier point also closes
    brackets, so the depth at the end of the string is the wrong thing to patch.

    Returns None when there is nothing salvageable.
    """
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
                # A complete top-level value: nothing to repair.
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
    """Best-effort parse of a model reply that is not quite valid JSON.

    Tries, in order: as-is, de-fenced, outermost braces only, trailing commas
    removed, truncation repaired. Returns None only when nothing works.
    """
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


# ── Client pool ───────────────────────────────────────────────────────────────

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_KEY_ENV_VARS = ("GOOGLE_AI_KEY", "GOOGLE_AI_KEY_2", "GOOGLE_AI_KEY_3")


def _build_clients() -> list[dict]:
    """One client + limiter per configured key. Labels are env var names, never key material."""
    clients = []
    for var in _KEY_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if not value:
            continue
        clients.append({
            "client": OpenAI(api_key=value, base_url=_GEMINI_BASE_URL, max_retries=0),
            "limiter": GoogleRateLimiter(),
            "key_label": var,
        })
        logger.info("Loaded API key from %s", var)
    if not clients:
        logger.critical("No GOOGLE_AI_KEY* env vars set — LLM extraction will fail")
    return clients


_clients = _build_clients()
_key_lock = threading.Lock()
_current_key_idx = 0


def _next_key_order() -> list[int]:
    """Key indices to try, starting from the one that last worked."""
    with _key_lock:
        start = _current_key_idx
    total = len(_clients)
    return [(start + offset) % total for offset in range(total)]


def _remember_key(idx: int) -> None:
    global _current_key_idx
    with _key_lock:
        _current_key_idx = idx


def daily_quota_exhausted() -> bool:
    """True only when every key's daily budget is spent."""
    return bool(_clients) and all(c["limiter"].daily_quota_exhausted() for c in _clients)


def total_requests_today() -> int:
    """Requests spent today across all keys."""
    return sum(c["limiter"].daily_count for c in _clients)


def _is_transient(error: str) -> bool:
    """True for errors worth trying on another key rather than giving up."""
    lowered = error.lower()
    return any(sig in lowered for sig in ("429", "503", "500", "rate", "unavailable",
                                          "overloaded", "timeout", "deadline exceeded"))


def _call_gemini(system_prompt: str, user_content: str, schema: dict, *,
                 source_url: str, response_name: str = "conference_extraction",
                 max_tokens: int = DEFAULT_MAX_TOKENS) -> dict | None:
    """One structured completion, rotating keys and repairing malformed JSON.

    Returns the parsed dict, or None when every key is exhausted or failing.
    """
    if not _clients:
        logger.error("extractor: no API keys available")
        return None

    for key_idx in _next_key_order():
        entry = _clients[key_idx]
        limiter, key_label = entry["limiter"], entry["key_label"]

        for attempt in range(1, MAX_ATTEMPTS_PER_KEY + 1):
            if limiter.daily_quota_exhausted():
                logger.info("extractor: key %s daily quota spent, rotating", key_label)
                break
            try:
                limiter.acquire()
            except RuntimeError:
                break

            try:
                logger.info("extractor: calling Gemini (key=%s) for %s (attempt %d, daily %d/%d)",
                            key_label, source_url, attempt,
                            limiter.daily_count, limiter.RPD_LIMIT)
                response = entry["client"].chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.0,
                    max_tokens=max_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": response_name, "schema": schema},
                    },
                )
            except Exception as e:
                message = str(e)
                if _is_transient(message):
                    logger.warning("extractor: transient error on key %s for %s — rotating: %s",
                                   key_label, source_url, message[:160])
                    break
                logger.error("extractor: API error for %s (attempt %d): %s",
                             source_url, attempt, message[:300])
                if attempt < MAX_ATTEMPTS_PER_KEY:
                    time.sleep(5)
                continue

            raw = response.choices[0].message.content
            parsed = repair_json(raw)
            if parsed is not None:
                _remember_key(key_idx)
                return parsed

            # Unrecoverable JSON is a model failure, not our quota's fault, but
            # it does consume an upstream request — do not refund the whole slot
            # more than once, or a persistently broken page loops forever.
            logger.error("extractor: unparseable reply for %s (attempt %d, %d chars)",
                         source_url, attempt, len(raw or ""))
            if attempt == 1:
                limiter.release_last()
                time.sleep(2)
                continue
            break

    logger.warning("extractor: all keys exhausted for %s", source_url)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def _format_previous_deadlines(previous_deadlines: dict) -> str | None:
    """Render stored deadlines as explicitly-untrusted context for re-extraction.

    Verification needs the model to notice a change, so the stored values are
    shown but flagged as possibly stale — otherwise the model tends to echo them.
    """
    if not previous_deadlines:
        return None
    lines = []
    for typ in DEADLINE_TYPES:
        old = previous_deadlines.get(typ)
        old_date = old.get("date") if isinstance(old, dict) else old
        if old_date:
            lines.append(f"  - {DEADLINE_LABELS.get(typ, typ)}: {old_date}")
    if not lines:
        return None
    return (
        "\n\nPreviously recorded deadlines from our database (these MAY BE OUTDATED — "
        "the page may have been updated since):\n"
        + "\n".join(lines)
        + "\nExtract the dates the page shows RIGHT NOW. Do not repeat a value above "
        "unless the page still displays it. If the page shows a later date for the "
        "same deadline, that is an extension — return the later date."
    )


def extract_conferences(page_text: str, source_url: str,
                        previous_deadlines: dict | None = None) -> dict | None:
    """Turn page text into a normalised conference dict, or None."""
    if not page_text or len(page_text.strip()) < MIN_PAGE_TEXT_CHARS:
        logger.warning("extractor: page text too short for %s, skipping", source_url)
        return None

    focused = focus_text(page_text, budget=MAX_TEXT_CHARS)
    if len(focused) < len(page_text):
        logger.info("extractor: focused %d chars down to %d for %s",
                    len(page_text), len(focused), source_url)

    user_content = f"Source URL: {source_url}\n\nPage content:\n{focused}"
    previous_block = _format_previous_deadlines(previous_deadlines)
    if previous_block:
        user_content += previous_block

    result = _call_gemini(SYSTEM_PROMPT, user_content, EXTRACTION_SCHEMA,
                          source_url=source_url)
    if result is None:
        return None

    result = normalize_extraction(result)
    logger.info("extractor: %s → is_conference=%s, confidence=%.2f, deadlines=%s",
                source_url, result.get("is_conference"), result.get("confidence", 0.0),
                {t: result.get(f"{t}_deadline") for t in DEADLINE_TYPES})
    return result


def extract(url, playwright: PlaywrightManager, previous_deadlines: dict | None = None,
            wait_until: str = "domcontentloaded"):
    """Fetch `url` and extract conference details from it.

    `wait_until="load"` is used by verification, where JS-rendered deadline
    timelines must have painted before the text is read.
    Returns the normalised dict, or None on any fetch/extraction failure.
    """
    from scraper.utils import is_safe_url

    if not is_safe_url(url):
        # is_safe_url resolves the hostname, so this doubles as the reachability
        # check that used to be a second, separate DNS lookup.
        logger.warning("extractor: unsafe or unresolvable URL, skipping: %s", url)
        return None

    text = playwright.fetch_page_text(url, wait_until=wait_until)
    if not text or len(text.strip()) < MIN_PAGE_TEXT_CHARS:
        logger.warning("extractor: could not read usable page text for %s", url)
        return None

    return extract_conferences(text, url, previous_deadlines=previous_deadlines)
