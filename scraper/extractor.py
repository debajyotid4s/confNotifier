import json
import logging
import os
import re
import socket
import time

from openai import OpenAI
from bs4 import BeautifulSoup

from scraper.browser import BrowserManager, load_page

# Note: time.sleep is no longer needed with single DeepSeek call, but kept for compatibility

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 8000

SYSTEM_PROMPT = (
    "You are a precise conference data extractor for Bangladesh.\n"
    "Given raw webpage text, extract international conference details.\n"
    "Return ONLY a valid JSON object. No explanation. No markdown. No backticks.\n"
    "{\n"
    '  "is_conference": true or false,\n'
    '  "title": "Full official conference title",\n'
    '  "date_start": "YYYY-MM-DD or null",\n'
    '  "date_end": "YYYY-MM-DD or null",\n'
    '  "city": "City in Bangladesh or null",\n'
    '  "country": "Bangladesh",\n'
    '  "website": "Full conference URL",\n'
    '  "organizer": "University or organization name or null",\n'
    '  "category": "One of: Engineering, Electrical, Computing, Civil, Biomedical, Business, Energy, Science, Agriculture, Medical, Textile, Other",\n'
    '  "confidence": 0.0 to 1.0\n'
    "}\n"
    "Rules:\n"
    "- is_conference = false for seminars, webinars, local events.\n"
    "- is_conference = true only for multi-day international conferences.\n"
    "- If held outside Bangladesh, is_conference = false."
)


def _strip_markdown_fence(text):
    """Remove markdown code fences and optional language tag from LLM output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


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


def _call_deepseek(text, url):
    """Send page text to DeepSeek API and return the parsed JSON response.

    Args:
        text: The page text content.
        url: The source URL (included in the prompt).

    Returns:
        Parsed JSON dict, or None on failure.
    """
    # Initialize client on demand with DeepSeek credentials
    client = OpenAI(
        api_key=os.getenv("DeepSeek_API_Token"),
        base_url="https://api.deepseek.com/v1"
    )
    
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"URL: {url}\n\nPage text:\n{text}",
                },
            ],
            temperature=0.0,
            max_tokens=1000,
        )
    except Exception as e:
        logger.error("DeepSeek API call failed: %s", e)
        return None

    raw = resp.choices[0].message.content
    if not raw:
        logger.warning("Empty response from DeepSeek")
        return None

    cleaned = _strip_markdown_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed: %s", e)
        return None

    return data


def extract(url):
    """Extract conference details from a candidate URL using DeepSeek API.

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
        logger.warning("Could not fetch page text for %s", url)
        return None

    logger.info("Extracting data from %s via DeepSeek", url)
    data = _call_deepseek(text, url)
    if data is not None:
        logger.info("DeepSeek extraction succeeded for %s", url)
        return data

    logger.warning("DeepSeek extraction failed for %s", url)
    return None
