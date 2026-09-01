"""scraper/extraction/client/pool.py — client pool and key rotation."""

import logging
import os
import threading

from openai import OpenAI

from scraper.extraction.client.config import _GEMINI_BASE_URL, _KEY_ENV_VARS
from scraper.extraction.rate_limiter import GoogleRateLimiter

logger = logging.getLogger(__name__)


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
