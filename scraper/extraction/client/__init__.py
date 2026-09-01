"""scraper/extraction/client — package facade."""

from scraper.extraction.client.config import (  # noqa: F401
    DEFAULT_MAX_TOKENS,
    MAX_ATTEMPTS_PER_KEY,
    MODEL,
    _GEMINI_BASE_URL,
    _KEY_ENV_VARS,
)
from scraper.extraction.client.gemini import _call_gemini, _is_transient, call_gemini  # noqa: F401

import scraper.extraction.client.pool as _pool  # noqa: F401

_build_clients = _pool._build_clients  # noqa: F401
_clients = _pool._clients  # noqa: F401
_next_key_order = _pool._next_key_order  # noqa: F401
_remember_key = _pool._remember_key  # noqa: F401
daily_quota_exhausted = _pool.daily_quota_exhausted  # noqa: F401
total_requests_today = _pool.total_requests_today  # noqa: F401


def __getattr__(name):  # PEP 562
    if name in ("_current_key_idx", "_key_lock"):
        return getattr(_pool, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["MODEL", "DEFAULT_MAX_TOKENS", "MAX_ATTEMPTS_PER_KEY", "_GEMINI_BASE_URL", "_KEY_ENV_VARS", "_build_clients", "_clients", "_key_lock", "_current_key_idx", "_next_key_order", "_remember_key", "call_gemini", "_call_gemini", "_is_transient", "daily_quota_exhausted", "total_requests_today"]
