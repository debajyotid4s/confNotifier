import logging
import os
from fastapi import APIRouter, Depends, HTTPException

from database import db_cursor, fetch_one
from mappers import user_row_to_out
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me")
def get_me(user=Depends(get_current_user)):
    row = fetch_one(
        "SELECT id, username, email, created_at FROM users WHERE id = %s AND deleted_at IS NULL",
        (user["sub"],),
    )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return user_row_to_out(row)


@router.delete("/me")
def delete_me(user=Depends(get_current_user)):
    uid = user["sub"]
    # Revoke first when Redis is configured — fail-fast before DB so we don't leave deleted user with valid token
    from cache import _is_redis_configured

    pre_bumped = False
    if _is_redis_configured():
        try:
            from cache import bump_token_version

            bump_token_version(uid)
            pre_bumped = True
        except Exception as e:
            logger.error("delete bump tv failed (Redis configured): %s", e)
            raise HTTPException(status_code=503, detail="Delete failed — try again")
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM bookmarks WHERE user_id = %s", (uid,))
        cur.execute("DELETE FROM device_tokens WHERE user_id = %s", (uid,))
        cur.execute("UPDATE users SET deleted_at = now() WHERE id = %s", (uid,))
    if not pre_bumped:
        try:
            from cache import bump_token_version

            bump_token_version(uid)
        except Exception as e:
            if os.environ.get("REDIS_URL"):
                logger.error("delete bump tv failed (Redis configured): %s", e)
                raise HTTPException(status_code=503, detail="Delete failed — try again")
            logger.warning("delete bump tv failed (no Redis): %s", e)
    logger.info("soft-deleted user %s", uid)
    return {"ok": True}
