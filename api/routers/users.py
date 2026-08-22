from fastapi import APIRouter, Depends, HTTPException
import psycopg2
from database import get_conn
from routers.auth import get_current_user

router = APIRouter()

@router.get("/me")
def get_me(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, email, created_at FROM users WHERE id = %s", (user["sub"],))
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        uid, username, email, created_at = row
        return {"id": str(uid), "username": username, "email": email, "created_at": created_at.isoformat() if created_at else None}
    finally:
        conn.close()

@router.delete("/me")
def delete_me(user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = %s", (user["sub"],))
        conn.commit()
        cur.close()
        try:
            from cache import bump_token_version
            bump_token_version(user["sub"])
        except Exception:
            pass
        return {"ok": True}
    finally:
        conn.close()
