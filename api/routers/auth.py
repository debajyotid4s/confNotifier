import logging
import os
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from pydantic import BaseModel
import psycopg2

from database import get_conn
from auth import verify_google_id_token, generate_username_candidate, create_jwt, decode_jwt

logger = logging.getLogger(__name__)
router = APIRouter()

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

@router.post("/auth/google")
def auth_google(body: GoogleAuthIn, request: Request):
    # Per-IP rate limiting: 10 req / 60s (Redis, fail-open if no Redis)
    try:
        from cache import check_rate_limit
        ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(f"rl:auth:google:{ip}", 10, 60):
            raise HTTPException(status_code=429, detail="Too many requests — try again later")
    except HTTPException:
        raise
    except Exception:
        pass
    info = verify_google_id_token(body.id_token)
    sub = info.get("sub")
    email = info.get("email")
    if not sub or not email:
        raise HTTPException(status_code=400, detail="Google token missing sub/email")
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    # Loop on INSERT conflict — UNIQUE is the authority, not SELECT pre-check
    for attempt in range(10):
        try:
            conn = get_conn()
            cur = conn.cursor()
            # Try lookup first
            cur.execute("SELECT id, username, email FROM users WHERE google_subject_id = %s", (sub,))
            row = cur.fetchone()
            if row:
                uid, username, db_email = row
                # Update last login info
                try:
                    cur.execute(
                        "UPDATE users SET last_login_at = now(), last_login_ip = %s, ip_address = %s, phone_model = COALESCE(%s, phone_model), user_agent = %s, device_info = COALESCE(%s, device_info) WHERE id = %s",
                        (client_ip, client_ip, body.phone_model, user_agent, body.device_info, uid)
                    )
                    conn.commit()
                except Exception as e:
                    logger.warning("auth_google: update login info failed for %s: %s", sub, e)
                    conn.rollback()
                cur.close(); conn.close()
                token = create_jwt(str(uid), db_email)
                logger.info("auth_google: login sub=%s username=%s ip=%s phone=%s", sub, username, client_ip, body.phone_model)
                return {"token": token, "user": {"id": str(uid), "username": username, "email": db_email}}
            # Not found → generate username and INSERT
            candidate = generate_username_candidate()
            try:
                cur.execute(
                    "INSERT INTO users (google_subject_id, email, username, phone_model, ip_address, user_agent, device_info, last_login_at, last_login_ip) VALUES (%s,%s,%s,%s,%s,%s,%s, now(), %s) RETURNING id, username",
                    (sub, email, candidate, body.phone_model, client_ip, user_agent, body.device_info, client_ip)
                )
                uid, username = cur.fetchone()
                conn.commit()
                cur.close(); conn.close()
                token = create_jwt(str(uid), email)
                logger.info("auth_google: created sub=%s username=%s ip=%s phone=%s", sub, username, client_ip, body.phone_model)
                return {"token": token, "user": {"id": str(uid), "username": username, "email": email}}
            except psycopg2.errors.UniqueViolation as e:
                conn.rollback()
                # Could be google_subject_id or username or email collision — retry
                # If it's google_subject_id, another concurrent request created it → loop will find it next iteration
                logger.warning("auth_google: unique violation attempt %d for %s: %s", attempt, candidate, e)
                cur.close(); conn.close()
                continue
        except HTTPException:
            raise
        except Exception as e:
            logger.error("auth_google error: %s", e)
            raise HTTPException(status_code=500, detail="auth failed")
    raise HTTPException(status_code=500, detail="Could not generate unique username")

class FirebaseAuthIn(BaseModel):
    id_token: str
    phone_model: str | None = None
    device_info: str | None = None

@router.post("/auth/firebase")
def auth_firebase(body: FirebaseAuthIn, request: Request):
    # Per-IP rate limiting: 10 req / 60s
    try:
        from cache import check_rate_limit
        ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(f"rl:auth:firebase:{ip}", 10, 60):
            raise HTTPException(status_code=429, detail="Too many requests — try again later")
    except HTTPException:
        raise
    except Exception:
        pass
    # Exchange Firebase ID token for app JWT — for email/password users
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
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    for attempt in range(10):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, username, email FROM users WHERE firebase_uid = %s", (fb_uid,))
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
                    logger.warning("auth_firebase update failed for %s: %s", fb_uid, e)
                    conn.rollback()
                cur.close(); conn.close()
                token = create_jwt(str(uid), db_email)
                logger.info("auth_firebase: login fb_uid=%s username=%s", fb_uid, username)
                return {"token": token, "user": {"id": str(uid), "username": username, "email": db_email}}
            candidate = generate_username_candidate()
            try:
                cur.execute(
                    "INSERT INTO users (firebase_uid, email, username, phone_model, ip_address, user_agent, device_info, last_login_at, last_login_ip) VALUES (%s,%s,%s,%s,%s,%s,%s, now(), %s) RETURNING id, username",
                    (fb_uid, email, candidate, body.phone_model, client_ip, user_agent, body.device_info, client_ip)
                )
                uid, username = cur.fetchone()
                conn.commit()
                cur.close(); conn.close()
                token = create_jwt(str(uid), email)
                logger.info("auth_firebase: created fb_uid=%s username=%s", fb_uid, username)
                return {"token": token, "user": {"id": str(uid), "username": username, "email": email}}
            except psycopg2.errors.UniqueViolation as e:
                conn.rollback()
                logger.warning("auth_firebase unique violation %d for %s: %s", attempt, candidate, e)
                cur.close(); conn.close()
                continue
        except HTTPException:
            raise
        except Exception as e:
            logger.error("auth_firebase error: %s", e)
            raise HTTPException(status_code=500, detail="auth failed")
    raise HTTPException(status_code=500, detail="Could not generate username")

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
