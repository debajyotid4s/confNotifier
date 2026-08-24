import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Depends, Header, Request
from pydantic import BaseModel
import psycopg2

from database import db_cursor, db_transaction, fetch_one
from auth import verify_google_id_token, generate_username_candidate, create_jwt, decode_jwt
from mappers import login_response

logger = logging.getLogger(__name__)
router = APIRouter()

def _client_ip(request: Request) -> str:
    # Trust XFF only when behind trusted proxy (Render, etc.). Default 1 for prod.
    # Set TRUST_PROXY=0 if running without proxy to avoid spoofed IP bypassing rate limit.
    if os.environ.get("TRUST_PROXY", "1") == "1":
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # XFF may be "client, proxy1, proxy2" — first is original client
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

class AuthLoginIn(BaseModel):
    provider: str  # "google" or "firebase"
    id_token: str
    phone_model: str | None = None
    device_info: str | None = None

def get_current_user(authorization: str = Header(None)):
    if not authorization or authorization.strip() == "" or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    # Extract token after "Bearer " and validate non-empty
    token = authorization[7:].strip() if len(authorization) > 7 else ""
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = decode_jwt(token)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("get_current_user: jwt decode failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload  # {sub, email, exp, iat, tv}


def get_optional_user(authorization: str = Header(None)):
    """For public endpoints: None if no header, 401 if header present but invalid."""
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token")
    token = authorization[7:].strip() if len(authorization) > 7 else ""
    if not token:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        payload = decode_jwt(token)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("get_optional_user: jwt decode failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload.get("sub")

def _rate_limit_or_429(request: Request, key_prefix: str):
    try:
        from cache import check_rate_limit
        ip = _client_ip(request)
        if not check_rate_limit(f"rl:auth:{key_prefix}:{ip}", 10, 60):
            raise HTTPException(status_code=429, detail="Too many requests — try again later")
    except HTTPException:
        raise
    except Exception:
        pass

GRACE_PERIOD_DAYS = 7
GRACE_PERIOD = timedelta(days=GRACE_PERIOD_DAYS)


def _grace_remaining_seconds(deleted_at: datetime, now: datetime) -> float:
    """Seconds until grace expires; >0 means still in grace."""
    # Ensure deleted_at is tz-aware (DB returns tz-aware TIMESTAMPTZ)
    if deleted_at.tzinfo is None:
        deleted_at = deleted_at.replace(tzinfo=timezone.utc)
    expires_at = deleted_at + GRACE_PERIOD
    return (expires_at - now).total_seconds()


def _upsert_user(*, lookup_col: str, lookup_val: str, email: str, body, client_ip, user_agent, log_id: str):
    """Shared upsert for Google and Firebase — single place for login-metadata handling."""
    if lookup_col not in ("google_subject_id", "firebase_uid"):
        raise ValueError(f"Invalid lookup_col: {lookup_col}")
    for attempt in range(10):
        try:
            row = fetch_one(f"SELECT id, username, email, deleted_at FROM users WHERE {lookup_col} = %s", (lookup_val,))
            if row:
                uid, username, db_email, deleted_at = row
                # Soft-deleted user: check grace period with precise interval (not floor days)
                if deleted_at is not None:
                    if deleted_at.tzinfo is None:
                        deleted_at = deleted_at.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    remaining_sec = _grace_remaining_seconds(deleted_at, now)
                    if remaining_sec > 0:
                        import math

                        remaining_days = math.ceil(remaining_sec / 86400)
                        days_since = (now - deleted_at).total_seconds() / 86400
                        # ceil ensures 6d23h shows as 1 day remaining, not 0
                        raise HTTPException(
                            status_code=403,
                            detail=f"Account was deleted {int(days_since)} day(s) ago. Contact admin to restore, or try again in {remaining_days} day(s).",
                        )
                    # Grace period expired — reactivate account
                    from database import execute

                    execute("UPDATE users SET deleted_at = NULL WHERE id = %s", (uid,))
                    logger.info("%s: reactivated user %s after grace period (deleted_at=%s)", log_id, uid, deleted_at)
                try:
                    from database import execute
                    execute(
                        "UPDATE users SET last_login_at = now(), last_login_ip = %s, ip_address = %s, phone_model = COALESCE(%s, phone_model), user_agent = %s, device_info = COALESCE(%s, device_info) WHERE id = %s",
                        (client_ip, client_ip, body.phone_model, user_agent, body.device_info, uid),
                    )
                except Exception as e:
                    logger.warning("%s: update login info failed for %s: %s", log_id, lookup_val, e)
                # History table (migration_004) — best-effort, don't block login
                try:
                    from database import execute as _exec_hist

                    _exec_hist(
                        "INSERT INTO login_events (user_id, ip_address, user_agent, phone_model, device_info) VALUES (%s,%s,%s,%s,%s)",
                        (uid, client_ip, user_agent, body.phone_model, body.device_info),
                    )
                except Exception as e:
                    logger.warning("%s: login_events insert failed for %s: %s", log_id, uid, e)
                token = create_jwt(str(uid), db_email)
                logger.info("%s: login %s=%s username=%s ip=%s phone=%s", log_id, lookup_col, lookup_val, username, client_ip, body.phone_model)
                return login_response(token, uid, username, db_email)
            candidate = generate_username_candidate()
            try:
                with db_transaction() as cur:
                    cur.execute(
                        f"INSERT INTO users ({lookup_col}, email, username, phone_model, ip_address, user_agent, device_info, last_login_at, last_login_ip) VALUES (%s,%s,%s,%s,%s,%s,%s, now(), %s) RETURNING id, username",
                        (lookup_val, email, candidate, body.phone_model, client_ip, user_agent, body.device_info, client_ip)
                    )
                    uid, username = cur.fetchone()
                # Initial login history for new user — best-effort
                try:
                    from database import execute as _exec_hist2

                    _exec_hist2(
                        "INSERT INTO login_events (user_id, ip_address, user_agent, phone_model, device_info) VALUES (%s,%s,%s,%s,%s)",
                        (uid, client_ip, user_agent, body.phone_model, body.device_info),
                    )
                except Exception as e:
                    logger.warning("%s: login_events insert failed for new %s: %s", log_id, uid, e)
                token = create_jwt(str(uid), email)
                logger.info("%s: created %s=%s username=%s ip=%s phone=%s", log_id, lookup_col, lookup_val, username, client_ip, body.phone_model)
                return login_response(token, uid, username, email)
            except psycopg2.errors.UniqueViolation as e:
                logger.warning("%s: unique violation attempt %d for %s: %s", log_id, attempt, candidate, e)
                continue
        except HTTPException:
            raise
        except Exception as e:
            logger.error("%s error: %s", log_id, e)
            raise HTTPException(status_code=500, detail="auth failed")
    raise HTTPException(status_code=500, detail="Could not generate unique username")

@router.post("/auth/login")
def auth_login(body: AuthLoginIn, request: Request):
    provider = body.provider
    if provider not in ("google", "firebase"):
        raise HTTPException(status_code=400, detail="provider must be 'google' or 'firebase'")

    _rate_limit_or_429(request, provider)
    client_ip = _client_ip(request)
    if client_ip == "unknown":
        client_ip = None
    user_agent = request.headers.get("user-agent")

    if provider == "google":
        info = verify_google_id_token(body.id_token)
        sub = info.get("sub")
        email = info.get("email")
        if not sub or not email:
            raise HTTPException(status_code=400, detail="Google token missing sub/email")
        return _upsert_user(lookup_col="google_subject_id", lookup_val=sub, email=email, body=body, client_ip=client_ip, user_agent=user_agent, log_id="auth_google")

    # firebase
    try:
        import firebase_admin.auth as fb_auth
        from routers.internal import _ensure_firebase
        _ensure_firebase()
        decoded = fb_auth.verify_id_token(body.id_token)
        fb_uid = decoded.get("uid")
        email = decoded.get("email")
        email_verified = decoded.get("email_verified", False)
        if not fb_uid or not email:
            raise HTTPException(status_code=400, detail="Firebase token missing uid/email")
        if not email_verified:
            raise HTTPException(status_code=403, detail="Email not verified — check your inbox")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("auth_firebase verify failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid Firebase token")
    return _upsert_user(lookup_col="firebase_uid", lookup_val=fb_uid, email=email, body=body, client_ip=client_ip, user_agent=user_agent, log_id="auth_firebase")

@router.post("/auth/logout")
def auth_logout(user=Depends(get_current_user)):
    try:
        from cache import bump_token_version
        bump_token_version(user.get("sub"))
    except Exception as e:
        if os.environ.get("REDIS_URL"):
            logger.error("logout bump tv failed (Redis configured): %s", e)
            raise HTTPException(status_code=503, detail="Logout failed — try again")
        logger.warning("logout bump tv failed (no Redis): %s", e)
    logger.info("logout sub=%s (token revoked)", user.get("sub"))
    return {"ok": True}
