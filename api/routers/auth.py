import logging
import os
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from pydantic import BaseModel
import psycopg2

from database import get_conn
from auth import verify_google_id_token, generate_username_candidate, create_jwt, decode_jwt

logger = logging.getLogger(__name__)
router = APIRouter()

def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

class GoogleAuthIn(BaseModel):
    id_token: str
    phone_model: str | None = None
    device_info: str | None = None

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt(token)
    except Exception as e:
        logger.warning("get_current_user: jwt decode failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload  # {sub, email, exp, iat}

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

def _upsert_user(*, lookup_col: str, lookup_val: str, email: str, body, client_ip, user_agent, log_id: str):
    """Shared upsert for Google (google_subject_id) and Firebase (firebase_uid).

    `lookup_col` must be a trusted column name (hardcoded caller), `lookup_val` is parameterized.
    Loops 10x on UniqueViolation (username collision) and returns {"token":..., "user":...}.
    """
    if lookup_col not in ("google_subject_id", "firebase_uid"):
        raise ValueError(f"Invalid lookup_col: {lookup_col}")
    for attempt in range(10):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(f"SELECT id, username, email FROM users WHERE {lookup_col} = %s", (lookup_val,))
            row = cur.fetchone()
            if row:
                uid, username, db_email = row
                try:
                    cur.execute(
                        "UPDATE users SET last_login_at = now(), last_login_ip = %s, ip_address = %s, phone_model = COALESCE(%s, phone_model), user_agent = %s, device_info = COALESCE(%s, device_info) WHERE id = %s",
                        (client_ip, client_ip, body.phone_model, user_agent, body.device_info, uid)
                    )
                    conn.commit()
                except Exception as e:
                    logger.warning("%s: update login info failed for %s: %s", log_id, lookup_val, e)
                    conn.rollback()
                cur.close(); conn.close()
                token = create_jwt(str(uid), db_email)
                logger.info("%s: login %s=%s username=%s ip=%s phone=%s", log_id, lookup_col, lookup_val, username, client_ip, body.phone_model)
                return {"token": token, "user": {"id": str(uid), "username": username, "email": db_email}}
            candidate = generate_username_candidate()
            try:
                cur.execute(
                    f"INSERT INTO users ({lookup_col}, email, username, phone_model, ip_address, user_agent, device_info, last_login_at, last_login_ip) VALUES (%s,%s,%s,%s,%s,%s,%s, now(), %s) RETURNING id, username",
                    (lookup_val, email, candidate, body.phone_model, client_ip, user_agent, body.device_info, client_ip)
                )
                uid, username = cur.fetchone()
                conn.commit()
                cur.close(); conn.close()
                token = create_jwt(str(uid), email)
                logger.info("%s: created %s=%s username=%s ip=%s phone=%s", log_id, lookup_col, lookup_val, username, client_ip, body.phone_model)
                return {"token": token, "user": {"id": str(uid), "username": username, "email": email}}
            except psycopg2.errors.UniqueViolation as e:
                conn.rollback()
                logger.warning("%s: unique violation attempt %d for %s: %s", log_id, attempt, candidate, e)
                cur.close(); conn.close()
                continue
        except HTTPException:
            raise
        except Exception as e:
            logger.error("%s error: %s", log_id, e)
            raise HTTPException(status_code=500, detail="auth failed")
    raise HTTPException(status_code=500, detail="Could not generate unique username")

@router.post("/auth/google")
def auth_google(body: GoogleAuthIn, request: Request):
    _rate_limit_or_429(request, "google")
    info = verify_google_id_token(body.id_token)
    sub = info.get("sub")
    email = info.get("email")
    if not sub or not email:
        raise HTTPException(status_code=400, detail="Google token missing sub/email")
    client_ip = _client_ip(request)
    if client_ip == "unknown":
        client_ip = None
    user_agent = request.headers.get("user-agent")
    return _upsert_user(lookup_col="google_subject_id", lookup_val=sub, email=email, body=body, client_ip=client_ip, user_agent=user_agent, log_id="auth_google")

class FirebaseAuthIn(BaseModel):
    id_token: str
    phone_model: str | None = None
    device_info: str | None = None

@router.post("/auth/firebase")
def auth_firebase(body: FirebaseAuthIn, request: Request):
    _rate_limit_or_429(request, "firebase")
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
    client_ip = _client_ip(request)
    if client_ip == "unknown":
        client_ip = None
    user_agent = request.headers.get("user-agent")
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
