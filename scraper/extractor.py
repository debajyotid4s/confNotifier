import json
import logging
import os
import re
import socket
import threading
import time
from collections import deque

from openai import OpenAI

from scraper.browser import PlaywrightManager

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
                    # At RPM limit — calculate exact wait time
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
_api_keys = []

for _var in ["GOOGLE_AI_KEY", "GOOGLE_AI_KEY_2", "GOOGLE_AI_KEY_3"]:
    _val = os.environ.get(_var, "").strip()
    if _val:
        _api_keys.append(_val)
        logger.info("Loaded API key from %s", _var)

if not _api_keys:
    logger.critical("No GOOGLE_AI_KEY* env vars set — LLM extraction will fail")

# Each key gets its own client + rate limiter
_clients = [
    {"client": OpenAI(api_key=k, base_url=_gemini_base_url, max_retries=0),
     "limiter": GoogleRateLimiter(),
     "key_hint": k[:8]}
    for k in _api_keys
]

_current_key_idx = 0

SYSTEM_PROMPT = """You are a precise conference data extractor for Bangladesh.
Given raw webpage text, extract international conference details.
Return ONLY a valid JSON object. No explanation. No markdown. No backticks.

{
  "is_conference": true or false,
  "title": "Full official conference title",
  "date_start": "YYYY-MM-DD or null",
  "date_end": "YYYY-MM-DD or null",
  "submission_deadline": "YYYY-MM-DD or null",
  "submission_deadline_label": "short label for what this date represents (e.g. 'Extended Abstract Submission', 'Paper Submission') or null",
  "submission_deadline_2": "YYYY-MM-DD or null",
  "submission_deadline_2_label": "short label for the second date (e.g. 'Full Paper Submission', 'Registration Deadline') or null",
  "city": "City in Bangladesh or null",
  "country": "Bangladesh",
  "website": "Full conference URL",
  "organizer": "University or organization name or null",
  "category": "One of: Engineering, Electrical, Computing, Civil, Biomedical, Business, Energy, Science, Agriculture, Medical, Textile, Other",
  "confidence": 0.0 to 1.0
}

Rules:
- is_conference = false for seminars, webinars, department pages, local events.
- is_conference = true only for multi-day international conferences.
- If held outside Bangladesh, is_conference = false.
- If page has no conference content, return is_conference = false.
- submission_deadline: the EARLIEST paper/abstract submission due date ONLY.
  Look for phrases like "submission deadline", "paper due", "last date of submission",
  "abstract submission", "full paper due", "call for papers deadline".
  ALSO scan the full text for date patterns like "Month DD, YYYY" (e.g. "August 02, 2026")
  and check if any date near text about "submission", "paper", "deadline" is the deadline.
  Dates may appear in visual timelines, infographics, or bullet lists — the date and its
  label might be on separate lines. Match dates to nearby labels by proximity.
  IMPORTANT: "Camera Ready", "Registration", "Author Registration", "Camera-Ready Submission"
  are NOT submission deadlines — they are post-acceptance steps. Never use these as submission_deadline.
  If not found, return null.
- submission_deadline_label: a short descriptive label for what the first deadline
  represents (e.g. "Extended Abstract Submission", "Paper Submission").
  If submission_deadline is null, this should also be null.
- submission_deadline_2: a SECOND submission deadline if the page mentions one
  (e.g. full paper deadline after extended abstract deadline).
  Must be a different date from submission_deadline.
  This is for multi-stage submission processes (abstract → full paper).
  Camera Ready, Registration, and Author Registration deadlines do NOT go here.
  If not found, return null.
- submission_deadline_2_label: a short descriptive label for the second deadline.
  If submission_deadline_2 is null, this should also be null."""


def _is_url_reachable(url: str) -> bool:
    """Quick DNS check before launching browser — avoids wasting time on dead sites."""
    try:
        hostname = url.replace("https://", "").replace("http://", "").split("/")[0]
        socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        return True
    except socket.gaierror:
        return False


def _fetch_page_text(url, playwright: PlaywrightManager):
    """Load a URL with Playwright and extract the visible text content.

    Args:
        url: The URL to fetch.
        playwright: Active PlaywrightManager instance (single browser for entire run).

    Returns:
        Extracted text content (first 8000 chars), or None on failure.
    """
    from scraper.sources.homepage_links import _is_safe_url
    if not _is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return None

    text = playwright.fetch_page_text(url)
    if text is None:
        logger.error("Failed to load candidate URL: %s", url)
        return None
    return text


def extract_conferences(page_text: str, source_url: str) -> dict | None:
    """
    Send page text to Gemini 2.5 Flash via Google AI Studio.

    Uses API key rotation — if one key hits 429, tries the next key.
    Only gives up if:
    - All keys' daily quotas are exhausted
    - API returns a non-rate-limit error after 3 attempts per key
    - Page text is empty
    
    Returns parsed dict or None.
    """
    global _current_key_idx

    if not page_text or len(page_text.strip()) < 100:
        logger.warning("extractor: page text too short for %s, skipping", source_url)
        return None

    if not _clients:
        logger.error("extractor: no API keys available")
        return None

    trimmed = page_text[:8000]
    max_attempts_per_key = 3
    total_keys = len(_clients)

    # Try each key, starting from current
    for key_offset in range(total_keys):
        key_idx = (_current_key_idx + key_offset) % total_keys
        entry = _clients[key_idx]
        client = entry["client"]
        limiter = entry["limiter"]
        key_hint = entry["key_hint"]

        for attempt in range(1, max_attempts_per_key + 1):
            # Check if this key's daily quota is exhausted — skip to next key
            if limiter.daily_quota_exhausted():
                logger.info("extractor: key %s daily quota exhausted, trying next key", key_hint)
                break

            try:
                limiter.acquire()
            except RuntimeError:
                break  # daily quota exhausted — try next key

            try:
                logger.info(
                    "extractor: calling Gemini (key=%s) for %s (attempt %d, daily: %d/%d)",
                    key_hint, source_url, attempt,
                    limiter._daily_count, limiter.RPD_LIMIT
                )

                response = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"Source URL: {source_url}\n\nPage content:\n{trimmed}"
                        }
                    ],
                    temperature=0.0,
                    max_tokens=4096,
                )

                raw = response.choices[0].message.content.strip()
                raw = re.sub(r"```json|```", "", raw).strip()
                result = json.loads(raw)
                logger.info(
                    "extractor: %s → is_conference=%s, confidence=%.2f",
                    source_url,
                    result.get("is_conference"),
                    result.get("confidence", 0.0),
                )
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
                        key_hint, source_url
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


def daily_quota_exhausted() -> bool:
    """Check if ALL keys have exhausted their daily quota."""
    return all(c["limiter"].daily_quota_exhausted() for c in _clients)


def total_requests_today() -> int:
    """Sum of daily request counts across all keys."""
    return sum(c["limiter"]._daily_count for c in _clients)


def extract(url, playwright: PlaywrightManager):
    """Extract conference details from a candidate URL using Gemini 2.5 Flash.

    Args:
        url: The candidate conference URL.
        playwright: Active PlaywrightManager instance.

    Returns:
        Dict with conference data if found, or None.
    """
    if not _is_url_reachable(url):
        logger.warning("extractor: DNS resolution failed for %s, skipping", url)
        return None

    text = _fetch_page_text(url, playwright)
    if text is None:
        logger.warning("extractor: could not fetch page text for %s", url)
        return None

    if len(text.strip()) < 100:
        logger.warning("extractor: page text too short for %s, skipping", url)
        return None

    logger.info("extractor: extracting from %s", url)
    return extract_conferences(text, url)
