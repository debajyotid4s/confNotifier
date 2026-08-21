import os
import random
import logging
from datetime import datetime, timedelta, timezone

from jose import jwt
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

logger = logging.getLogger(__name__)

# Session strategy: JWT-stateless (no server store). Logout is client-side delete;
# we don't maintain a blacklist — token lives until expiry (7 days). Stated per spec.
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"
JWT_EXP_DAYS = 7

ADJECTIVES = ["Quiet","Bright","Calm","Swift","Bold","Kind","Wise","Neat","Lively","Hazy","Cool","Warm","Merry","Sly","Keen","Gentle","Amber","Crimson","Silver","Golden"]
NOUNS = ["Comet","River","Forest","Falcon","Panda","Tiger","Ocean","Meadow","Summit","Harbor","Canyon","Valley","Aurora","Echo","Beacon","Voyager","Pixel","Vector","Orbit","Quark"]

def verify_google_id_token(id_token_str: str) -> dict:
    """Verify against Google's public keys server-side. Never trust client claims."""
    # In dev without real Google token, allow GOOGLE_AUTH_DISABLE=1 for testing
    if os.environ.get("GOOGLE_AUTH_DISABLE") == "1":
        logger.warning("GOOGLE_AUTH_DISABLE=1 — skipping Google verification (dev only)")
        # Expect id_token_str to be a JSON with sub/email for dev testing
        import json
        try:
            return json.loads(id_token_str)
        except Exception:
            return {"sub": id_token_str[:32], "email": f"{id_token_str[:8]}@test.local"}
    req = google_requests.Request()
    # aud: allow any — we don't have a single Google client ID yet; verify signature + expiry only
    info = google_id_token.verify_oauth2_token(id_token_str, req)
    # info contains sub, email, etc.
    logger.info("Google token verified sub=%s email=%s", info.get("sub"), info.get("email"))
    return info

def generate_username_candidate() -> str:
    return f"{random.choice(ADJECTIVES)}{random.choice(NOUNS)}{random.randint(10,99)}"

def create_jwt(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXP_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def decode_jwt(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
