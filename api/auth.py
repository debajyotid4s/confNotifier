import os
import secrets
import logging
from datetime import datetime, timedelta, timezone

from jose import jwt
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

logger = logging.getLogger(__name__)

JWT_ALG = "HS256"
JWT_EXP_DAYS = 7


def _get_jwt_secret() -> str:
    s = os.environ.get("JWT_SECRET")
    if not s:
        raise RuntimeError("JWT_SECRET env var is required — set a strong random value, no fallback")
    return s
# For revocation: token_version per user (Redis user:{id}:tv), embedded in JWT as `tv`

ADJECTIVES = ["Quiet","Bright","Calm","Swift","Bold","Kind","Wise","Neat","Lively","Hazy","Cool","Warm","Merry","Sly","Keen","Gentle","Amber","Crimson","Silver","Golden"]
NOUNS = ["Comet","River","Forest","Falcon","Panda","Tiger","Ocean","Meadow","Summit","Harbor","Canyon","Valley","Aurora","Echo","Beacon","Voyager","Pixel","Vector","Orbit","Quark"]

def verify_google_id_token(id_token_str: str) -> dict:
    """Verify against Google's public keys server-side. Never trust client claims."""
    if os.environ.get("GOOGLE_AUTH_DISABLE") == "1":
        # Fail-closed in production — this flag must never ship to prod
        env = os.environ.get("ENV", os.environ.get("RENDER_ENV", "production" if os.environ.get("RENDER") else "development"))
        if env == "production":
            logger.error("GOOGLE_AUTH_DISABLE=1 blocked in production env=%s", env)
            raise RuntimeError("GOOGLE_AUTH_DISABLE not allowed in production")
        logger.warning("GOOGLE_AUTH_DISABLE=1 — skipping Google verification (dev only, env=%s)", env)
        import json
        try:
            return json.loads(id_token_str)
        except Exception:
            return {"sub": id_token_str[:32], "email": f"{id_token_str[:8]}@test.local"}
    req = google_requests.Request()
    aud = os.environ.get("WEB_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID")
    if not aud:
        raise RuntimeError("WEB_CLIENT_ID (or GOOGLE_CLIENT_ID) env var is required for Google verification")
    info = google_id_token.verify_oauth2_token(id_token_str, req, audience=aud)
    # Log that verification succeeded, not who it was for: the full email and
    # Google subject id used to be written to the application log on every login.
    logger.info("Google token verified (sub=%s…)", str(info.get("sub", ""))[:6])
    return info

def generate_username_candidate() -> str:
    return f"{secrets.choice(ADJECTIVES)}{secrets.choice(NOUNS)}{secrets.randbelow(90)+10}"

def create_jwt(user_id: str, email: str) -> str:
    # Embed token_version for revocation (Redis user:{id}:tv) — fail-closed when Redis configured but unavailable
    tv = 0
    try:
        from cache import get_token_version, _is_redis_configured, get_redis

        if _is_redis_configured() and get_redis() is None:
            logger.error("create_jwt fail-closed for %s: Redis configured but unavailable", user_id)
            raise RuntimeError("Redis unavailable — cannot issue token")
        tv = get_token_version(user_id)
        # Re-check Redis still available after tv fetch (race)
        if _is_redis_configured() and get_redis() is None:
            logger.error("create_jwt fail-closed after tv fetch for %s: Redis became unavailable", user_id)
            raise RuntimeError("Redis unavailable — cannot issue token")
    except RuntimeError:
        raise
    except Exception:
        # No Redis configured (dev) — allow tv=0; or transient error logged inside get_token_version
        pass
    payload = {
        "sub": user_id,
        "email": email,
        "tv": tv,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXP_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALG)

def decode_jwt(token: str) -> dict:
    payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALG])
    # Check revocation: tv must match current version
    # Fail-closed when Redis is configured but unavailable (prevents revoked token reuse)
    try:
        from cache import get_token_version, _is_redis_configured
        from cache import get_redis as _get_redis_check

        if _is_redis_configured():
            r = _get_redis_check()
            if r is None:
                logger.error("decode_jwt fail-closed for sub=%s: Redis configured but unavailable", payload.get("sub"))
                raise jwt.JWTError("Token revoked - auth store unavailable")
        current = get_token_version(payload.get("sub", ""))
        # Re-check after get_token_version: if Redis went down between the two calls, fail closed
        if _is_redis_configured() and _get_redis_check() is None:
            logger.error("decode_jwt fail-closed for sub=%s: Redis became unavailable", payload.get("sub"))
            raise jwt.JWTError("Token revoked - auth store unavailable")
        if payload.get("tv", 0) != current:
            raise jwt.JWTError("Token revoked")
    except jwt.JWTError:
        raise
    except Exception as e:
        if os.environ.get("REDIS_URL"):
            logger.warning("decode_jwt error for sub=%s: %s", payload.get("sub"), e)
            raise jwt.JWTError("Token verification unavailable")
        pass
    return payload
