"""Redis helpers: cache-aside reads, rate limiting, JWT revocation counters.

Everything degrades gracefully when REDIS_URL is unset (local development) or
Redis is unreachable: reads go straight to Postgres and rate limiting fails open.
The one exception is token revocation, which fails *closed* — see auth.py.

Cache invalidation uses a generation counter rather than key scanning. The old
`invalidate_prefix` walked every key in the database with SCAN and deleted matches,
three times per scraper run. Bumping one integer invalidates a whole namespace in
a single command, because the generation is part of every key.
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_redis = None
_redis_available = None   # None = not yet tried, True/False = last known state
_redis_last_try = 0.0

#: How long to wait before retrying a connection that failed.
RECONNECT_BACKOFF_SECONDS = 30
CONNECT_TIMEOUT = 2

#: Namespaces whose keys carry a generation number.
_CONFERENCE_NAMESPACES = ("cal", "upcoming", "conf")


def _is_redis_configured() -> bool:
    return bool(os.environ.get("REDIS_URL"))


def get_redis():
    """Shared Redis client, or None when unconfigured or unreachable."""
    global _redis, _redis_available, _redis_last_try

    if not _is_redis_configured():
        _redis_available = False
        return None
    if _redis_available is False and (time.time() - _redis_last_try) < RECONNECT_BACKOFF_SECONDS:
        return None
    if _redis is not None and _redis_available:
        return _redis

    _redis_last_try = time.time()
    try:
        import redis

        _redis = redis.from_url(
            os.environ["REDIS_URL"],
            decode_responses=True,
            socket_connect_timeout=CONNECT_TIMEOUT,
            socket_timeout=CONNECT_TIMEOUT,
        )
        _redis.ping()
        _redis_available = True
        logger.info("Redis connected")
        return _redis
    except Exception as e:
        logger.warning("Redis unavailable (%s) — caching and rate limiting degraded", e)
        _redis_available = False
        return None


# ── Generation-based invalidation ─────────────────────────────────────────────

def _generation(namespace: str) -> int:
    """Current generation for a cache namespace."""
    redis = get_redis()
    if redis is None:
        return 0
    try:
        value = redis.get(f"gen:{namespace}")
        return int(value) if value is not None else 0
    except Exception as e:
        logger.warning("Redis generation read failed for %s: %s", namespace, e)
        return 0


def invalidate_conference_reads() -> None:
    """Invalidate all cached conference responses after a scraper write.

    Bumps the generation of every conference namespace in one pipeline: old
    entries are not deleted, they simply become unreachable and expire on their
    own TTL — no SCAN, no per-key DELETE.
    """
    redis = get_redis()
    if redis is None:
        return
    try:
        pipe = redis.pipeline()
        for namespace in _CONFERENCE_NAMESPACES:
            pipe.incr(f"gen:{namespace}")
        pipe.execute()
        logger.info("invalidated conference read caches")
    except Exception as e:
        logger.warning("conference cache invalidation failed: %s", e)


# ── Cache-aside ───────────────────────────────────────────────────────────────

def get_or_set(key: str, producer, ttl: int = 300):
    """Return the cached value for `key`, else call `producer()` and cache it.

    `key` is "<namespace>:<suffix>"; the stored key has the namespace generation
    spliced in, so `invalidate_conference_reads()` supersedes every entry without
    deleting anything. Exceptions from `producer` propagate and are never cached.
    """
    redis = get_redis()
    if redis is None:
        return producer()

    namespace, _, suffix = key.partition(":")
    generation = _generation(namespace)
    full_key = f"{namespace}:v{generation}:{suffix}" if suffix else f"{namespace}:v{generation}"

    try:
        cached = redis.get(full_key)
        if cached is not None:
            return json.loads(cached)
    except Exception as e:
        logger.warning("Redis GET %s failed: %s", full_key, e)

    value = producer()
    try:
        # set(..., ex=) rather than the deprecated setex(name, time, value) form.
        redis.set(full_key, json.dumps(value, default=str), ex=ttl)
    except Exception as e:
        logger.warning("Redis SET %s failed: %s", full_key, e)
    return value


# ── Rate limiting ─────────────────────────────────────────────────────────────

def check_rate_limit(key: str, limit: int, window_sec: int) -> bool:
    """True when the request is allowed.

    Fixed-window counter: INCR, and set the TTL on the first hit of a window.
    Fails open — an unavailable Redis must not lock every user out.
    """
    redis = get_redis()
    if redis is None:
        if _is_redis_configured():
            logger.warning("rate limit %s failing open: Redis unavailable", key)
        return True
    try:
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        # A key with no expiry would count forever; repair it.
        if ttl is None or ttl < 0:
            redis.expire(key, window_sec)
        return count <= limit
    except Exception as e:
        logger.warning("Redis rate limit %s failed: %s", key, e)
        return True


# ── JWT revocation ────────────────────────────────────────────────────────────

def get_token_version(user_id: str) -> int:
    """Current token generation for a user. Tokens with an older `tv` are revoked."""
    redis = get_redis()
    if redis is None:
        if _is_redis_configured():
            logger.warning("get_token_version failing open for %s: Redis unavailable", user_id)
        return 0
    try:
        value = redis.get(f"user:{user_id}:tv")
        return int(value) if value is not None else 0
    except Exception as e:
        logger.warning("get_token_version failed for %s: %s", user_id, e)
        return 0


def bump_token_version(user_id: str) -> int:
    """Revoke every existing token for a user.

    Raises when Redis is configured but unavailable: silently failing to revoke on
    logout or account deletion would leave a valid token in the wild.
    """
    redis = get_redis()
    if redis is None:
        if _is_redis_configured():
            raise RuntimeError("Redis unavailable — cannot revoke token")
        return 0
    try:
        return redis.incr(f"user:{user_id}:tv")
    except Exception as e:
        logger.warning("Redis token revocation failed for %s: %s", user_id, e)
        raise
