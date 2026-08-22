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

def get_redis():
    global _redis, _redis_available
    if _redis_available is not None:
        return _redis
    url = os.environ.get("REDIS_URL")
    if not url:
        _redis_available = False
        return None
    try:
        import redis
        _redis = redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        _redis.ping()
        _redis_available = True
        logger.info("Redis connected")
        return _redis
    except Exception as e:
        logger.warning("Redis unavailable (%s) — caching/rate-limit disabled", e)
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

def check_rate_limit(key: str, limit: int, window_sec: int) -> bool:
    """
    Return True if allowed, False if rate-limited.
    Uses INCR + EXPIRE. No Redis → allow (fail open in dev).
    """
    r = get_redis()
    if r is None:
        return True
    try:
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        if ttl == -1:
            r.expire(key, window_sec)
        return count <= limit
    except Exception as e:
        logger.warning("Redis rate limit %s failed: %s", key, e)
        return True

# Token version for JWT revocation (Redis user:{id}:tv)
def get_token_version(user_id: str) -> int:
    r = get_redis()
    if r is None:
        return 0
    try:
        v = r.get(f"user:{user_id}:tv")
        return int(v) if v is not None else 0
    except Exception:
        return 0

def bump_token_version(user_id: str) -> int:
    r = get_redis()
    if r is None:
        return 0
    try:
        return r.incr(f"user:{user_id}:tv")
    except Exception as e:
        logger.warning("Redis bump tv %s failed: %s", user_id, e)
        return 0
