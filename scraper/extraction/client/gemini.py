"""scraper/extraction/client/gemini.py — Gemini call with rotation."""

import logging
import time

from scraper.extraction.client.config import DEFAULT_MAX_TOKENS, MAX_ATTEMPTS_PER_KEY, MODEL
from scraper.extraction.client.pool import _clients, _next_key_order, _remember_key
from scraper.extraction.json_repair import repair_json

logger = logging.getLogger(__name__)


def _is_transient(error: str) -> bool:
    """True for errors worth trying on another key rather than giving up."""
    lowered = error.lower()
    return any(sig in lowered for sig in ("429", "503", "500", "rate", "unavailable", "overloaded", "timeout", "deadline exceeded"))


def call_gemini(system_prompt: str, user_content: str, schema: dict, *, source_url: str, response_name: str = "conference_extraction", max_tokens: int = DEFAULT_MAX_TOKENS) -> dict | None:
    """One structured completion, rotating keys and repairing malformed JSON."""
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
                logger.info("extractor: calling Gemini (key=%s) for %s (attempt %d, daily %d/%d)", key_label, source_url, attempt, limiter.daily_count, limiter.RPD_LIMIT)
                response = entry["client"].chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
                    temperature=0.0,
                    max_tokens=max_tokens,
                    response_format={"type": "json_schema", "json_schema": {"name": response_name, "schema": schema}},
                )
            except Exception as e:
                message = str(e)
                if _is_transient(message):
                    logger.warning("extractor: transient error on key %s for %s — rotating: %s", key_label, source_url, message[:160])
                    break
                logger.error("extractor: API error for %s (attempt %d): %s", source_url, attempt, message[:300])
                if attempt < MAX_ATTEMPTS_PER_KEY:
                    time.sleep(5)
                continue
            raw = response.choices[0].message.content
            parsed = repair_json(raw)
            if parsed is not None:
                _remember_key(key_idx)
                return parsed
            logger.error("extractor: unparseable reply for %s (attempt %d, %d chars)", source_url, attempt, len(raw or ""))
            if attempt == 1:
                limiter.release_last()
                time.sleep(2)
                continue
            break
    logger.warning("extractor: all keys exhausted for %s", source_url)
    return None


_call_gemini = call_gemini  # legacy alias
