from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import db_cursor
from routers.auth import get_current_user

router = APIRouter()

class DeviceIn(BaseModel):
    fcm_token: str

@router.post("/me/devices", status_code=201)
def upsert_device(body: DeviceIn, user=Depends(get_current_user)):
    token = body.fcm_token.strip() if body.fcm_token else ""
    if not token or len(token) < 10 or len(token) > 500:
        raise HTTPException(status_code=400, detail="Invalid fcm_token")
    with db_cursor(commit=True) as cur:
        # Single-transaction upsert with RETURNING to avoid race.
        # ON CONFLICT DO UPDATE ... WHERE user_id = EXCLUDED.user_id:
        # - same user -> updates updated_at and RETURNING yields row
        # - other user -> WHERE false -> no update, rowcount 0, no RETURNING row
        cur.execute(
            """
            INSERT INTO device_tokens (user_id, fcm_token, updated_at)
            VALUES (%s,%s, now())
            ON CONFLICT (fcm_token) DO UPDATE SET updated_at=now() WHERE device_tokens.user_id = EXCLUDED.user_id
            RETURNING id
            """,
            (user["sub"], token),
        )
        ret = cur.fetchone()
        if ret is not None:
            # Inserted or same-user update succeeded
            return {"ok": True}
        # No RETURNING row -> token exists but owned by other user (rowcount 0 path)
        # Check within same tx to ensure consistent read (no separate connection race)
        cur.execute("SELECT user_id FROM device_tokens WHERE fcm_token=%s", (token,))
        row = cur.fetchone()
        if row and str(row[0]) != str(user["sub"]):
            raise HTTPException(status_code=409, detail="Token already registered to another user")
        if row is None:
            # Concurrent delete between INSERT and SELECT — retry once
            cur.execute(
                """
                INSERT INTO device_tokens (user_id, fcm_token, updated_at)
                VALUES (%s,%s, now())
                ON CONFLICT (fcm_token) DO UPDATE SET updated_at=now() WHERE device_tokens.user_id = EXCLUDED.user_id
                RETURNING id
                """,
                (user["sub"], token),
            )
            ret2 = cur.fetchone()
            if ret2 is not None:
                return {"ok": True}
            raise HTTPException(status_code=500, detail="Failed to register device, try again")
        # Same-user row exists but WHERE false shouldn't happen — treat as success after ensuring row
        return {"ok": True}

@router.delete("/me/devices/{token}", status_code=204)
def delete_device(token: str, user=Depends(get_current_user)):
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM device_tokens WHERE fcm_token=%s AND user_id=%s", (token, user["sub"]))
    return
