import json
import logging
import os
import re
import socket
import threading
import time
from collections import deque

from openai import OpenAI
from bs4 import BeautifulSoup

from scraper.browser import BrowserManager, load_page

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 8000
MODEL = "gemini-2.5-flash"


class GoogleRateLimiter:
    """
    Enforces Google AI Studio free tier limits:
    - Max 15 requests per 60-second rolling window (RPM)
    - Max 1500 requests per calendar day (RPD)
    Thread-safe. Blocks the caller until a slot is available.
    """

    RPM_LIMIT = 15
    RPD_LIMIT = 1500
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
        Waits for RPM window to clear if at 15 req/min.
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
                "Rate limiter: at 15 RPM, waiting %.1fs for slot "
                "(daily used: %d/%d)",
                wait_seconds, self._daily_count, self.RPD_LIMIT
            )
            time.sleep(max(wait_seconds, 0.5))


# Single shared instance used by all extraction calls
_rate_limiter = GoogleRateLimiter()

# OpenAI client pointed at Google AI Studio
_google_key = os.environ.get("GOOGLE_AI_KEY", "")
if not _google_key:
    logger.critical("GOOGLE_AI_KEY is not set — LLM extraction will fail")
else:
    logger.info("GOOGLE_AI_KEY loaded (%s...)", _google_key[:8])

google_client = OpenAI(
    api_key=_google_key or "MISSING",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

SYSTEM_PROMPT = """You are a precise conference data extractor for Bangladesh.
Given raw webpage text, extract international conference details.
Return ONLY a valid JSON object. No explanation. No markdown. No backticks.

{
  "is_conference": true or false,
  "title": "Full official conference title",
  "date_start": "YYYY-MM-DD or null",
  "date_end": "YYYY-MM-DD or null",
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
- If page has no conference content, return is_conference = false."""


def _is_url_reachable(url: str) -> bool:
    """Quick DNS check before launching Selenium — avoids wasting time on dead sites."""
    try:
        hostname = url.replace("https://", "").replace("http://", "").split("/")[0]
        socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        return True
    except socket.gaierror:
        return False


def _fetch_page_text(url):
    """Load a URL with Selenium and extract the visible text content.

    Args:
        url: The URL to fetch.

    Returns:
        Extracted text content (first 8000 chars), or None on failure.
    """
    from scraper.sources.homepage_links import _is_safe_url
    if not _is_safe_url(url):
        logger.warning("SSRF blocked: %s", url)
        return None

    with BrowserManager() as driver:
        if not load_page(driver, url):
            logger.error("Failed to load candidate URL: %s", url)
            return None
        html = driver.page_source
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:MAX_TEXT_CHARS]


def extract_conferences(page_text: str, source_url: str) -> dict | None:
    """
    Send page text to Gemini 2.5 Flash via Google AI Studio.

    NEVER gives up due to rate limits — waits as long as needed.
    Only gives up if:
    - Daily quota is fully exhausted (1500 requests)
    - API returns a non-rate-limit error after 3 attempts
    - Page text is empty
    
    Returns parsed dict or None.
    """
    if not page_text or len(page_text.strip()) < 100:
        logger.warning("extractor: page text too short for %s, skipping", source_url)
        return None

    trimmed = page_text[:8000]
    max_non_ratelimit_attempts = 3

    for attempt in range(1, max_non_ratelimit_attempts + 1):
        # This blocks until a rate limit slot is available
        # Raises RuntimeError only if daily quota is exhausted
        try:
            _rate_limiter.acquire()
        except RuntimeError as e:
            logger.error("extractor: %s", e)
            return None

        try:
            logger.info(
                "extractor: calling Gemini 2.5 Flash for %s (attempt %d, daily used: %d/%d)",
                source_url, attempt, _rate_limiter._daily_count, _rate_limiter.RPD_LIMIT
            )

            response = google_client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Source URL: {source_url}\n\nPage content:\n{trimmed}"
                    }
                ],
                temperature=0.0,
                max_tokens=1000,
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
            return result

        except json.JSONDecodeError as e:
            logger.error(
                "extractor: JSON parse failed for %s (attempt %d): %s",
                source_url, attempt, e
            )
            # JSON errors are model output issues — retry makes sense
            time.sleep(2)
            continue

        except Exception as e:
            err_str = str(e)

            # 429 should not reach here since acquire() handles RPM waiting,
            # but handle it defensively anyway
            if "429" in err_str or "rate" in err_str.lower():
                wait = 65  # wait a full minute then retry
                logger.warning(
                    "extractor: unexpected 429 for %s, waiting %ds...",
                    source_url, wait
                )
                time.sleep(wait)
                continue

            # Any other API error
            logger.error(
                "extractor: API error for %s (attempt %d): %s",
                source_url, attempt, e
            )
            if attempt < max_non_ratelimit_attempts:
                time.sleep(5)
                continue
            return None

    logger.warning("extractor: all attempts exhausted for %s", source_url)
    return None


def extract(url):
    """Extract conference details from a candidate URL using Gemini 2.5 Flash.

    Args:
        url: The candidate conference URL.

    Returns:
        Dict with conference data if found, or None.
    """
    if not _is_url_reachable(url):
        logger.warning("extractor: DNS resolution failed for %s, skipping", url)
        return None

    text = _fetch_page_text(url)
    if text is None:
        logger.warning("extractor: could not fetch page text for %s", url)
        return None

    logger.info("extractor: extracting from %s", url)
    return extract_conferences(text, url)
