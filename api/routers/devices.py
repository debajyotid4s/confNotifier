from fastapi import APIRouter, Depends
from pydantic import BaseModel
from database import get_conn
from routers.auth import get_current_user

router = APIRouter()

class DeviceIn(BaseModel):
    fcm_token: str

@router.post("/me/devices", status_code=201)
def upsert_device(body: DeviceIn, user=Depends(get_current_user)):
    token = body.fcm_token.strip() if body.fcm_token else ""
    if not token or len(token) < 10 or len(token) > 500:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid fcm_token")
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Prevent hijack: only update if token already owned by same user
        cur.execute(
            """
            INSERT INTO device_tokens (user_id, fcm_token, updated_at)
            VALUES (%s,%s, now())
            ON CONFLICT (fcm_token) DO UPDATE SET updated_at=now() WHERE device_tokens.user_id = EXCLUDED.user_id
            """,
            (user["sub"], token)
        )
        # If token exists for another user, rowcount will be 0 (no update) and we should not claim it
        if cur.rowcount == 0:
            # Check if token exists for another user
            cur.execute("SELECT user_id FROM device_tokens WHERE fcm_token=%s", (token,))
            row = cur.fetchone()
            if row and str(row[0]) != str(user["sub"]):
                from fastapi import HTTPException
                raise HTTPException(status_code=409, detail="Token already registered to another user")
        conn.commit()
        cur.close()
        return {"ok": True}
    finally:
        try:
            conn.close()
        except Exception:
            pass

@router.delete("/me/devices/{token}", status_code=204)
def delete_device(token: str, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM device_tokens WHERE fcm_token=%s AND user_id=%s", (token, user["sub"]))
        conn.commit()
        cur.close()
        return
    finally:
        conn.close()
