import os
import random
import logging
from datetime import datetime, timedelta, timezone

from jose import jwt
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

logger = logging.getLogger(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET env var is required — set a strong random value, no fallback")
JWT_ALG = "HS256"
JWT_EXP_DAYS = 7
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
    logger.info("Google token verified sub=%s email=%s aud=%s", info.get("sub"), info.get("email"), info.get("aud"))
    return info

def generate_username_candidate() -> str:
    return f"{random.choice(ADJECTIVES)}{random.choice(NOUNS)}{random.randint(10,99)}"

def create_jwt(user_id: str, email: str) -> str:
    # Embed token_version for revocation (Redis user:{id}:tv)
    tv = 0
    try:
        from cache import get_token_version
        tv = get_token_version(user_id)
    except Exception:
        pass
    payload = {
        "sub": user_id,
        "email": email,
        "tv": tv,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXP_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def decode_jwt(token: str) -> dict:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    # Check revocation: tv must match current version
    try:
        from cache import get_token_version
        current = get_token_version(payload.get("sub", ""))
        if payload.get("tv", 0) != current:
            raise jwt.JWTError("Token revoked")
    except jwt.JWTError:
        raise
    except Exception as e:
        # Redis down → fail open but visible
        if os.environ.get("REDIS_URL"):
            logger.warning("decode_jwt fail-open for sub=%s: Redis unavailable (%s)", payload.get("sub"), e)
        pass
    return payload
