"""
Thin Redis helper — get_or_set + rate limiting + token_version.
Falls back to no-op if REDIS_URL not set (dev without Redis).
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

_redis = None
_redis_available = None  # None=unknown, True/False
_redis_last_try = 0

def _is_redis_configured() -> bool:
    return bool(os.environ.get("REDIS_URL"))

def get_redis():
    global _redis, _redis_available, _redis_last_try
    import time
    # If not configured, fail fast (dev without Redis)
    if not _is_redis_configured():
        _redis_available = False
        return None
    # If previously failed, retry after 30s instead of caching forever
    if _redis_available is False and (time.time() - _redis_last_try) < 30:
        return None
    if _redis is not None and _redis_available is True:
        return _redis
    _redis_last_try = time.time()
    url = os.environ.get("REDIS_URL")
    try:
        import redis
        _redis = redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        _redis.ping()
        _redis_available = True
        logger.info("Redis connected")
        return _redis
    except Exception as e:
        logger.warning("Redis unavailable (%s) — caching/rate-limit degraded", e)
        _redis_available = False
        return None

def get_or_set(key: str, fn, ttl: int = 300):
    """
    Cache-aside helper: return cached JSON if present, else fn() and cache.
    fn should be a zero-arg callable returning a JSON-serializable value.
    """
    r = get_redis()
    if r is None:
        return fn()
    try:
        cached = r.get(key)
        if cached is not None:
            return json.loads(cached)
    except Exception as e:
        logger.warning("Redis GET %s failed: %s", key, e)
    val = fn()
    try:
        r.setex(key, ttl, json.dumps(val, default=str))
    except Exception as e:
        logger.warning("Redis SETEX %s failed: %s", key, e)
    return val

def invalidate_prefix(prefix: str):
    r = get_redis()
    if r is None:
        return
    try:
        for k in r.scan_iter(match=prefix + "*"):
            r.delete(k)
    except Exception as e:
        logger.warning("Redis invalidate %s* failed: %s", prefix, e)


def invalidate_exact(key: str):
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception as e:
        logger.warning("Redis delete %s failed: %s", key, e)


def invalidate_conf(conference_id: int):
    """Invalidate cached conference detail for a given id — exact + per-user variants."""
    # Exact unauth key `conf:{id}` + per-user `conf:{id}:*` without colliding `conf:1` vs `conf:10`
    invalidate_exact(f"conf:{conference_id}")
    invalidate_prefix(f"conf:{conference_id}:")

def check_rate_limit(key: str, limit: int, window_sec: int) -> bool:
    """
    Return True if allowed, False if rate-limited.
    Uses INCR; first increment sets EXPIRE. No Redis → allow (fail open in dev).
    """
    r = get_redis()
    if r is None:
        if _is_redis_configured():
            logger.warning("rate limit %s fail-open: Redis configured but unavailable", key)
        return True
    try:
        count = r.incr(key)
        if count == 1:
            r.expire(key, window_sec)
        else:
            # Ensure TTL exists even if key was created without expiry (e.g., TTL stripped) — must check every hit for correctness
            try:
                ttl = r.ttl(key)
                if ttl == -1:
                    r.expire(key, window_sec)
            except Exception:
                pass
        return count <= limit
    except Exception as e:
        logger.warning("Redis rate limit %s failed: %s", key, e)
        return True

# Token version for JWT revocation (Redis user:{id}:tv)
def get_token_version(user_id: str) -> int:
    r = get_redis()
    if r is None:
        if _is_redis_configured():
            logger.warning("get_token_version fail-open for %s: Redis configured but unavailable", user_id)
        return 0
    try:
        v = r.get(f"user:{user_id}:tv")
        return int(v) if v is not None else 0
    except Exception as e:
        logger.warning("get_token_version failed for %s: %s", user_id, e)
        return 0

def bump_token_version(user_id: str) -> int:
    r = get_redis()
    if r is None:
        if _is_redis_configured():
            raise RuntimeError("Redis unavailable — cannot revoke token")
        return 0
    try:
        return r.incr(f"user:{user_id}:tv")
    except Exception as e:
        logger.warning("Redis bump tv %s failed: %s", user_id, e)
        raise
