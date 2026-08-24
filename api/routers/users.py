import logging
import os
from fastapi import APIRouter, Depends, HTTPException

from database import db_cursor, fetch_one
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/me")
def get_me(user=Depends(get_current_user)):
    row = fetch_one("SELECT id, username, email, created_at FROM users WHERE id = %s", (user["sub"],))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    uid, username, email, created_at = row
    return {"id": str(uid), "username": username, "email": email, "created_at": created_at.isoformat() if created_at else None}

@router.delete("/me")
def delete_me(user=Depends(get_current_user)):
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (user["sub"],))
    try:
        from cache import bump_token_version
        bump_token_version(user["sub"])
    except Exception as e:
        if os.environ.get("REDIS_URL"):
            logger.error("delete bump tv failed (Redis configured): %s", e)
            raise HTTPException(status_code=503, detail="Delete failed — try again")
        logger.warning("delete bump tv failed (no Redis): %s", e)
    return {"ok": True}
