"""scraper/extraction/client.py — Gemini client pool + key rotation."""

import logging
import os
import threading
import time

from openai import OpenAI

from scraper.extraction.json_repair import repair_json
from scraper.extraction.rate_limiter import GoogleRateLimiter

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
DEFAULT_MAX_TOKENS = 4096
MAX_ATTEMPTS_PER_KEY = 3

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_KEY_ENV_VARS = ("GOOGLE_AI_KEY", "GOOGLE_AI_KEY_2", "GOOGLE_AI_KEY_3")


def _build_clients() -> list[dict]:
    """One client + limiter per configured key."""
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


_call_gemini = call_gemini  # legacy alias for scraper/extractor import (change_detector)
