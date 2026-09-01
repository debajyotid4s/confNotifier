import logging

from scraper.extractor import _call_gemini

from .constants import VERDICT_PROMPT, VERDICT_SCHEMA, VERDICTS

logger = logging.getLogger(__name__)


def classify_homepage(domain: str, page_text: str, prev_links: list[str]) -> dict | None:
    """Ask Gemini why a previously productive homepage went quiet."""
    prev_block = "\n".join(f"  - {u}" for u in prev_links[:10]) or "  (none)"
    user_content = (
        f"Domain: {domain}\n\n"
        f"Previously discovered conference links:\n{prev_block}\n\n"
        f"Current page text:\n{page_text[:4000]}"
    )
    try:
        result = _call_gemini(
            VERDICT_PROMPT, user_content, VERDICT_SCHEMA,
            source_url=domain, response_name="homepage_change_verdict",
            max_tokens=400,
        )
    except Exception as e:
        logger.error("change_detector: classify error for %s: %s", domain, e)
        return None
    if not result or result.get("verdict") not in VERDICTS:
        logger.warning("change_detector: unexpected classification for %s: %r", domain, result)
        return None
    return result
