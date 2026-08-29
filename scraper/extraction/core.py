"""scraper/extraction/core.py — public extract() API."""

import logging

from scraper.browser import PlaywrightManager
from scraper.extraction.client import call_gemini
from scraper.schema import DEADLINE_LABELS, DEADLINE_TYPES, EXTRACTION_SCHEMA, SYSTEM_PROMPT, normalize_extraction
from scraper.textfocus import focus_text

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 14000
MIN_PAGE_TEXT_CHARS = 100


def _format_previous_deadlines(previous_deadlines: dict) -> str | None:
    """Render stored deadlines as explicitly-untrusted context for re-extraction."""
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


def extract_conferences(page_text: str, source_url: str, previous_deadlines: dict | None = None) -> dict | None:
    """Turn page text into a normalised conference dict, or None."""
    if not page_text or len(page_text.strip()) < MIN_PAGE_TEXT_CHARS:
        logger.warning("extractor: page text too short for %s, skipping", source_url)
        return None
    focused = focus_text(page_text, budget=MAX_TEXT_CHARS)
    if len(focused) < len(page_text):
        logger.info("extractor: focused %d chars down to %d for %s", len(page_text), len(focused), source_url)
    user_content = f"Source URL: {source_url}\n\nPage content:\n{focused}"
    previous_block = _format_previous_deadlines(previous_deadlines)
    if previous_block:
        user_content += previous_block
    result = call_gemini(SYSTEM_PROMPT, user_content, EXTRACTION_SCHEMA, source_url=source_url)
    if result is None:
        return None
    result = normalize_extraction(result)
    logger.info("extractor: %s → is_conference=%s, confidence=%.2f, deadlines=%s", source_url, result.get("is_conference"), result.get("confidence", 0.0), {t: result.get(f"{t}_deadline") for t in DEADLINE_TYPES})
    return result


def extract(url, playwright: PlaywrightManager, previous_deadlines: dict | None = None, wait_until: str = "domcontentloaded"):
    """Fetch `url` and extract conference details from it."""
    from scraper.utils import is_safe_url
    if not is_safe_url(url):
        logger.warning("extractor: unsafe or unresolvable URL, skipping: %s", url)
        return None
    text = playwright.fetch_page_text(url, wait_until=wait_until)
    if not text or len(text.strip()) < MIN_PAGE_TEXT_CHARS:
        logger.warning("extractor: could not read usable page text for %s", url)
        return None
    return extract_conferences(text, url, previous_deadlines=previous_deadlines)
