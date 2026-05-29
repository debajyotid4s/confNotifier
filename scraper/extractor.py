import json
import logging
import os
import re
import time

from openai import OpenAI
from bs4 import BeautifulSoup

from scraper.browser import BrowserManager, load_page

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-4-26b-a4b-it:free",
    "deepseek/deepseek-v4-flash:free",
]
MAX_TEXT_CHARS = 8000
TIMEOUT_SEC = 60

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


def _call_llm(text, url, model):
    """Send page text to an OpenRouter model and return the parsed JSON response.

    Args:
        text: The page text content.
        url: The source URL (included in the prompt).
        model: The OpenRouter model name.

    Returns:
        Parsed JSON dict, or None on failure.
    """
    client = OpenAI(
        base_url=OPENROUTER_BASE,
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=TIMEOUT_SEC,
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"URL: {url}\n\nPage text:\n{text}",
                },
            ],
            temperature=0.1,
            max_tokens=1000,
        )
    except Exception as e:
        logger.warning("OpenRouter call failed for model %s: %s", model, e)
        return None

    raw = resp.choices[0].message.content
    if not raw:
        logger.warning("Empty response from model %s", model)
        return None

    cleaned = _strip_markdown_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed for model %s: %s", model, e)
        return None

    return data


def extract(url):
    """Extract conference details from a candidate URL using LLM.

    Tries each model in the configured order until one succeeds.
    Returns the parsed JSON data, or None if all models fail.

    Args:
        url: The candidate conference URL.

    Returns:
        Dict with conference data if found, or None.
    """
    text = _fetch_page_text(url)
    if text is None:
        logger.warning("Could not fetch page text for %s", url)
        return None

    for model in MODELS:
        logger.info("Trying model %s for %s", model, url)
        data = _call_llm(text, url, model)
        if data is not None:
            logger.info("Model %s succeeded for %s", model, url)
            return data
        time.sleep(1)

    logger.warning("All models failed for %s", url)
    return None
