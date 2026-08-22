import os
import json
import hmac
import logging
from fastapi import APIRouter, Header, HTTPException
from database import get_conn

logger = logging.getLogger(__name__)
router = APIRouter()

# Firebase Admin lazy init — expects FIREBASE_SERVICE_ACCOUNT_JSON (JSON string) or
# FIREBASE_SERVICE_ACCOUNT_JSON_B64 or a file at /etc/secrets/firebase.json (Render)
_firebase_inited = False

def _ensure_firebase():
    global _firebase_inited
    if _firebase_inited:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials
        # Already inited?
        try:
            firebase_admin.get_app()
            _firebase_inited = True
            return True
        except ValueError:
            pass
        # Try env var JSON
        sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON_B64")
        if sa_json:
            # Handle base64
            if sa_json.strip().startswith("{"):
                info = json.loads(sa_json)
            else:
                import base64
                info = json.loads(base64.b64decode(sa_json).decode())
            cred = credentials.Certificate(info)
            firebase_admin.initialize_app(cred)
            _firebase_inited = True
            logger.info("Firebase Admin inited from env")
            return True
        # Try file (Render secret file)
        for p in ["/etc/secrets/firebase.json", "firebase-service-account.json"]:
            if os.path.exists(p):
                cred = credentials.Certificate(p)
                firebase_admin.initialize_app(cred)
                _firebase_inited = True
                logger.info("Firebase Admin inited from %s", p)
                return True
        logger.warning("Firebase Admin not configured — no service account found (set FIREBASE_SERVICE_ACCOUNT_JSON)")
        return False
    except Exception as e:
        logger.warning("Firebase Admin init failed: %s", e)
        return False

# Choice per spec Phase 2.2: POST /internal/notify-scraper-run with shared secret
# Requires fewer changes to confNotifier workflow than direct FCM from that repo
# (just add `curl -H "X-Notify-Secret: $NOTIFY_SECRET" $API/internal/notify-scraper-run` after UPSERT).

@router.post("/internal/notify-scraper-run")
def notify_scraper_run(x_notify_secret: str = Header(None)):
    expected = os.environ.get("NOTIFY_SECRET", "")
    if not expected or not x_notify_secret or not hmac.compare_digest(x_notify_secret, expected):
        raise HTTPException(status_code=401, detail="Invalid secret")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT fcm_token FROM device_tokens")
        tokens = [r[0] for r in cur.fetchall() if r[0]]
        cur.close()
        count = len(tokens)
        logger.info("notify-scraper-run: %d device(s) to notify (daily digest)", count)
        # Invalidate cached conference reads — scraper just upserted
        try:
            from cache import invalidate_prefix
            invalidate_prefix("cal:")
            invalidate_prefix("upcoming:")
            invalidate_prefix("conf:")
        except Exception:
            pass
        if count == 0:
            return {"ok": True, "devices": 0, "sent": 0, "message": "No devices"}
        if not _ensure_firebase():
            return {"ok": True, "devices": count, "sent": 0, "message": "Check today's conference updates (FCM not configured)"}
        # Send via FCM — single daily digest, defer per-conference diff
        try:
            import firebase_admin.messaging as fcm
            # FCM multicast max 500 per call
            sent = 0
            for i in range(0, len(tokens), 500):
                batch = tokens[i:i+500]
                msg = fcm.MulticastMessage(
                    notification=fcm.Notification(title="Call4Paper", body="Check today's conference updates"),
                    data={"type": "daily_digest", "screen": "calendar"},
                    tokens=batch,
                )
                resp = fcm.send_each_for_multicast(msg)
                sent += resp.success_count
                if resp.failure_count:
                    logger.warning("FCM batch %d: %d failures", i//500, resp.failure_count)
            logger.info("FCM daily digest sent to %d/%d", sent, count)
            return {"ok": True, "devices": count, "sent": sent, "message": "Check today's conference updates"}
        except Exception as e:
            logger.error("FCM send failed: %s", e)
            raise HTTPException(status_code=500, detail=f"FCM failed: {e}")
    finally:
        conn.close()
