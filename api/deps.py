"""Shared FastAPI dependencies: internal auth, rate limiting, security headers.

The internal secret check was duplicated in all four `/internal/*` handlers, and
the public conference endpoints had no rate limit at all — on a free-tier Render
instance backed by a free-tier Neon database, an unauthenticated loop over
`/conferences/upcoming` is enough to exhaust both.
"""

import hmac
import logging
import os

from fastapi import Header, HTTPException, Request

logger = logging.getLogger(__name__)

#: Requests per window for unauthenticated read endpoints, per client IP.
PUBLIC_RATE_LIMIT = 60
PUBLIC_RATE_WINDOW = 60

#: Auth attempts per window per client IP.
AUTH_RATE_LIMIT = 10
AUTH_RATE_WINDOW = 60

#: Internal endpoints are called by cron, so the limit only needs to stop a loop.
INTERNAL_RATE_LIMIT = 10
INTERNAL_RATE_WINDOW = 300


def client_ip(request: Request) -> str:
    """Best-effort client address.

    X-Forwarded-For is only trusted when TRUST_PROXY is on (the default, since we
    deploy behind Render's proxy). With TRUST_PROXY=0 the header is ignored, so a
    direct-exposed deployment cannot have its rate limit bypassed by spoofing it.
    """
    if os.environ.get("TRUST_PROXY", "1") == "1":
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # "client, proxy1, proxy2" — the leftmost entry is the origin client.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(key: str, limit: int, window: int) -> None:
    """Raise 429 when `key` exceeds `limit` requests per `window` seconds.

    Fails open when Redis is unavailable: degrading to unlimited reads is better
    than returning errors for every request, and the check is defence in depth
    rather than the only protection.
    """
    try:
        from cache import check_rate_limit

        if not check_rate_limit(key, limit, window):
            raise HTTPException(status_code=429, detail="Too many requests — try again later")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("rate limit check failed for %s: %s", key, e)


def public_rate_limit(request: Request) -> None:
    """Dependency: throttle anonymous reads per IP."""
    enforce_rate_limit(f"rl:pub:{client_ip(request)}", PUBLIC_RATE_LIMIT, PUBLIC_RATE_WINDOW)


def require_internal_secret(request: Request, x_notify_secret: str = Header(None)) -> None:
    """Dependency: gate `/internal/*` behind the shared secret.

    Compared with `hmac.compare_digest` so the check is not timing-dependent, and
    rate-limited so a leaked-secret guessing loop cannot also be a DoS.
    """
    expected = os.environ.get("NOTIFY_SECRET", "")
    if not expected:
        # No secret configured means the endpoint is unprotected — refuse rather
        # than silently accept every caller.
        logger.error("NOTIFY_SECRET is not set — refusing internal request")
        raise HTTPException(status_code=503, detail="Internal endpoints not configured")

    enforce_rate_limit(f"rl:int:{client_ip(request)}", INTERNAL_RATE_LIMIT, INTERNAL_RATE_WINDOW)

    if not x_notify_secret or not hmac.compare_digest(x_notify_secret, expected):
        logger.warning("internal request rejected: bad secret from %s", client_ip(request))
        raise HTTPException(status_code=401, detail="Invalid secret")
