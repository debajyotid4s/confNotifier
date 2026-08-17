import json
import logging
import os
import socket
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

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 8000
MODEL = "gemini-2.5-flash"


class GoogleRateLimiter:
    """
    Enforces Google AI Studio free tier limits for Gemini 2.5 Flash:
    - Max 5 requests per 60-second rolling window (RPM)
    - Max 20 requests per calendar day (RPD)
    Thread-safe. Blocks the caller until a slot is available.
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

    def daily_quota_exhausted(self) -> bool:
        with self._lock:
            self._reset_daily_if_needed()
            return self._daily_count >= self.RPD_LIMIT

    def acquire(self):
        """
        Block until a request slot is available.
        Waits for RPM window to clear if at limit.
        Raises RuntimeError if daily quota is exhausted.
        """
        while True:
            wait_seconds = 0.0
            with self._lock:
                self._reset_daily_if_needed()

                if self._daily_count >= self.RPD_LIMIT:
                    raise RuntimeError(
                        f"Daily quota exhausted: {self._daily_count}/{self.RPD_LIMIT} "
                        f"requests used today. Remaining candidates will be processed "
                        f"tomorrow."
                    )

                # Warn when approaching daily limit (80% threshold)
                if self._daily_count >= int(self.RPD_LIMIT * 0.8) and self._daily_count < self.RPD_LIMIT:
                    logger.warning(
                        "Rate limiter: daily quota at %d/%d (%d%%) — approaching limit",
                        self._daily_count, self.RPD_LIMIT,
                        int(self._daily_count / self.RPD_LIMIT * 100)
                    )

                now = time.time()
                cutoff = now - self.WINDOW_SECONDS

                # Remove timestamps outside the rolling window
                while self._request_timestamps and self._request_timestamps[0] < cutoff:
                    self._request_timestamps.popleft()

                if len(self._request_timestamps) < self.RPM_LIMIT:
                    # Slot available — record and proceed
                    self._request_timestamps.append(now)
                    self._daily_count += 1
                    return
                else:
                    # At RPM limit — calculate exact wait time (do NOT record yet)
                    oldest_in_window = self._request_timestamps[0]
                    wait_seconds = (oldest_in_window + self.WINDOW_SECONDS) - now + 0.5

            # Wait outside the lock
            logger.info(
                "Rate limiter: at %d RPM, waiting %.1fs for slot "
                "(daily used: %d/%d)",
                self.RPM_LIMIT, wait_seconds, self._daily_count, self.RPD_LIMIT
            )
            time.sleep(max(wait_seconds, 0.5))


# ── API key rotation — load all available keys ──

_gemini_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
_api_keys = []  # (env var name, key value) — name is the non-secret log label

for _var in ["GOOGLE_AI_KEY", "GOOGLE_AI_KEY_2", "GOOGLE_AI_KEY_3"]:
    _val = os.environ.get(_var, "").strip()
    if _val:
        _api_keys.append((_var, _val))
        logger.info("Loaded API key from %s", _var)

if not _api_keys:
    logger.critical("No GOOGLE_AI_KEY* env vars set — LLM extraction will fail")

# Each key gets its own client + rate limiter
_clients = [
    {"client": OpenAI(api_key=k, base_url=_gemini_base_url, max_retries=0),
     "limiter": GoogleRateLimiter(),
     "key_label": name}
    for name, k in _api_keys
]

_current_key_idx = 0


def _is_url_reachable(url: str) -> bool:
    """Quick DNS check before launching browser — avoids wasting time on dead sites."""
    try:
        hostname = url.replace("https://", "").replace("http://", "").split("/")[0]
        socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        return True
    except socket.gaierror:
        return False


def _fetch_page_text(url, playwright: PlaywrightManager, wait_until: str = "domcontentloaded"):
    """Load a URL with Playwright and extract the visible text content.

    Args:
        url: The URL to fetch.
        playwright: Active PlaywrightManager instance (single browser for entire run).
        wait_until: Playwright wait condition. "domcontentloaded" for speed,
                    "load" for pages whose deadlines render via JS after DOM ready.

    Returns:
        Extracted text content (first 8000 chars), or None on failure.
    """
    from scraper.utils import is_safe_url
    if not is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return None

    text = playwright.fetch_page_text(url, wait_until=wait_until)
    if text is None:
        logger.error("Failed to load candidate URL: %s", url)
        return None
    return text


def _format_previous_deadlines(previous_deadlines: dict) -> str | None:
    """Render previously stored deadlines as 'may be outdated' context for the LLM."""
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
        "\n\nPreviously recorded deadlines from our database (may be OUTDATED — "
        "the website may have been updated):\n"
        + "\n".join(lines)
        + "\nIMPORTANT: Extract the CURRENT dates shown on the page right now. "
        "Do NOT repeat the previously recorded values unless the page still displays them."
    )


def _call_gemini(
    system_prompt: str,
    user_content: str,
    schema: dict,
    *,
    source_url: str,
    response_name: str = "conference_extraction",
    max_tokens: int = 4096,
) -> dict | None:
    """Single LLM completion with API key rotation and rate limiting.

    Tries each key in round-robin order starting from the last working one.
    Within a key, retries up to 3 times on non-rate-limit errors. Gives up
    when all keys fail or every key's daily quota is exhausted.

    Returns the parsed JSON dict, or None.
    """
    global _current_key_idx

    if not _clients:
        logger.error("extractor: no API keys available")
        return None

    max_attempts_per_key = 3
    total_keys = len(_clients)

    # Try each key, starting from current
    for key_offset in range(total_keys):
        key_idx = (_current_key_idx + key_offset) % total_keys
        entry = _clients[key_idx]
        client = entry["client"]
        limiter = entry["limiter"]
        key_label = entry["key_label"]

        for attempt in range(1, max_attempts_per_key + 1):
            # Check if this key's daily quota is exhausted — skip to next key
            if limiter.daily_quota_exhausted():
                logger.info("extractor: key %s daily quota exhausted, trying next key", key_label)
                break

            try:
                limiter.acquire()
            except RuntimeError:
                break  # daily quota exhausted — try next key

            try:
                logger.info(
                    "extractor: calling Gemini (key=%s) for %s (attempt %d, daily: %d/%d)",
                    key_label, source_url, attempt,
                    limiter._daily_count, limiter.RPD_LIMIT
                )

                response = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.0,
                    max_tokens=max_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": response_name,
                            "schema": schema,
                        },
                    },
                )

                result = json.loads(response.choices[0].message.content)
                _current_key_idx = key_idx  # remember last working key
                return result

            except json.JSONDecodeError as e:
                logger.error(
                    "extractor: JSON parse failed for %s (attempt %d): %s",
                    source_url, attempt, e
                )
                time.sleep(2)
                continue

            except Exception as e:
                err_str = str(e)

                if "429" in err_str or "rate" in err_str.lower() or "503" in err_str or "UNAVAILABLE" in err_str:
                    logger.warning(
                        "extractor: transient error (%s) on key %s for %s, rotating to next key",
                        "429" if "429" in err_str else "503",
                        key_label, source_url
                    )
                    break  # break inner loop → try next key

                logger.error(
                    "extractor: API error for %s (attempt %d): %s",
                    source_url, attempt, e
                )
                if attempt < max_attempts_per_key:
                    time.sleep(5)
                    continue

    logger.warning("extractor: all keys exhausted for %s", source_url)
    return None


def extract_conferences(page_text: str, source_url: str, previous_deadlines: dict | None = None) -> dict | None:
    """
    Send page text to Gemini 2.5 Flash via Google AI Studio.

    Uses API key rotation — if one key hits 429, tries the next key.
    Only gives up if:
    - All keys' daily quotas are exhausted
    - API returns a non-rate-limit error after 3 attempts per key
    - Page text is empty

    Args:
        page_text: Visible text of the page.
        source_url: The URL that was fetched.
        previous_deadlines: Optional {type: {date, label}} of what we had stored,
                            passed so the LLM anchors on the CURRENT page values.

    Returns parsed dict or None.
    """
    if not page_text or len(page_text.strip()) < 100:
        logger.warning("extractor: page text too short for %s, skipping", source_url)
        return None

    trimmed = page_text[:MAX_TEXT_CHARS]
    user_content = f"Source URL: {source_url}\n\nPage content:\n{trimmed}"
    previous_block = _format_previous_deadlines(previous_deadlines)
    if previous_block:
        user_content += previous_block

    result = _call_gemini(
        SYSTEM_PROMPT,
        user_content,
        EXTRACTION_SCHEMA,
        source_url=source_url,
    )
    if result is None:
        return None

    result = normalize_extraction(result)
    logger.info(
        "extractor: %s → is_conference=%s, confidence=%.2f",
        source_url,
        result.get("is_conference"),
        result.get("confidence", 0.0),
    )
    return result


def daily_quota_exhausted() -> bool:
    """Check if ALL keys have exhausted their daily quota."""
    return all(c["limiter"].daily_quota_exhausted() for c in _clients)


def total_requests_today() -> int:
    """Sum of daily request counts across all keys."""
    return sum(c["limiter"]._daily_count for c in _clients)


def extract(url, playwright: PlaywrightManager, previous_deadlines: dict | None = None,
            wait_until: str = "domcontentloaded"):
    """Extract conference details from a candidate URL using Gemini 2.5 Flash.

    Args:
        url: The candidate conference URL.
        playwright: Active PlaywrightManager instance.
        previous_deadlines: Optional {type: {date, label}} of what we had stored,
                            passed so the LLM anchors on the CURRENT page values
                            (used by deadline verification).
        wait_until: Playwright wait condition — "domcontentloaded" (default) or
                    "load" when JS-rendered deadline timelines must be present.

    Returns:
        Dict with conference data if found, or None.
    """
    if not _is_url_reachable(url):
        logger.warning("extractor: DNS resolution failed for %s, skipping", url)
        return None

    text = _fetch_page_text(url, playwright, wait_until=wait_until)
    if text is None:
        logger.warning("extractor: could not fetch page text for %s", url)
        return None

    if len(text.strip()) < 100:
        logger.warning("extractor: page text too short for %s, skipping", url)
        return None

    logger.info("extractor: extracting from %s", url)
    return extract_conferences(text, url, previous_deadlines=previous_deadlines)
