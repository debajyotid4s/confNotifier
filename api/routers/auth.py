import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import psycopg2

from database import get_conn
from auth import verify_google_id_token, generate_username_candidate, create_jwt, decode_jwt

logger = logging.getLogger(__name__)
router = APIRouter()

class GoogleAuthIn(BaseModel):
    id_token: str

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    return payload  # {sub, email, exp, iat}

@router.post("/auth/google")
def auth_google(body: GoogleAuthIn):
    info = verify_google_id_token(body.id_token)
    sub = info.get("sub")
    email = info.get("email")
    if not sub or not email:
        raise HTTPException(status_code=400, detail="Google token missing sub/email")
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
                cur.close(); conn.close()
                token = create_jwt(str(uid), db_email)
                logger.info("auth_google: login sub=%s username=%s", sub, username)
                return {"token": token, "user": {"id": str(uid), "username": username, "email": db_email}}
            # Not found → generate username and INSERT
            candidate = generate_username_candidate()
            try:
                cur.execute(
                    "INSERT INTO users (google_subject_id, email, username) VALUES (%s,%s,%s) RETURNING id, username",
                    (sub, email, candidate)
                )
                uid, username = cur.fetchone()
                conn.commit()
                cur.close(); conn.close()
                token = create_jwt(str(uid), email)
                logger.info("auth_google: created sub=%s username=%s", sub, username)
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

@router.post("/auth/logout")
def auth_logout(user=Depends(get_current_user)):
    # JWT-stateless: no server store, logout is client discarding token
    logger.info("logout sub=%s", user.get("sub"))
    return {"ok": True}
