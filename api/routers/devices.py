from fastapi import APIRouter, Depends
from pydantic import BaseModel
from database import get_conn
from routers.auth import get_current_user

router = APIRouter()

class DeviceIn(BaseModel):
    fcm_token: str

@router.post("/me/devices", status_code=201)
def upsert_device(body: DeviceIn, user=Depends(get_current_user)):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO device_tokens (user_id, fcm_token, updated_at)
            VALUES (%s,%s, now())
            ON CONFLICT (fcm_token) DO UPDATE SET user_id=EXCLUDED.user_id, updated_at=now()
            """,
            (user["sub"], body.fcm_token)
        )
        conn.commit()
        cur.close()
        return {"ok": True}
    finally:
        conn.close()

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
