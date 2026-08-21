import os
import logging
from fastapi import APIRouter, Header, HTTPException
from database import get_conn

logger = logging.getLogger(__name__)
router = APIRouter()

# Choice per spec Phase 2.2: POST /internal/notify-scraper-run with shared secret
# Requires fewer changes to confNotifier workflow than direct FCM from that repo
# (just add `curl -H "X-Notify-Secret: $NOTIFY_SECRET" $API/internal/notify-scraper-run` after UPSERT).

@router.post("/internal/notify-scraper-run")
def notify_scraper_run(x_notify_secret: str = Header(None)):
    expected = os.environ.get("NOTIFY_SECRET", "")
    if not expected or x_notify_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid secret")
    # For Phase 2: single daily "Check today's conference updates" push
    # Defer per-conference diff to later iteration
    # Here we just log and count device_tokens; actual FCM send requires Firebase Admin SDK
    # For now, return count so workflow can verify hook fired
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM device_tokens")
        count = cur.fetchone()[0]
        cur.close()
        logger.info("notify-scraper-run: %d device(s) would be notified (daily digest)", count)
        # TODO: integrate firebase-admin to send FCM when credentials available
        return {"ok": True, "devices": count, "message": "Check today's conference updates"}
    finally:
        conn.close()
