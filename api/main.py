from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from routers import auth as auth_router
from routers import users as users_router
from routers import conferences as conf_router
from routers import bookmarks as bm_router
from routers import devices as dev_router
from routers import internal as internal_router

# Logging — guard against double basicConfig when imported in tests
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Call4Paper API", version="0.1.0")

import os

# Restrict CORS — wildcard + credentials is rejected by browsers and overly permissive
def _get_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "https://confnotifier.onrender.com,http://localhost:3000,http://127.0.0.1:8000")
    return [o.strip() for o in raw.split(",") if o.strip()]


_cors_origins = _get_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(conf_router.router)
app.include_router(bm_router.router)
app.include_router(dev_router.router)
app.include_router(internal_router.router)

@app.get("/health")
def health():
    checks = {"ok": True}
    # DB
    try:
        from database import fetch_one
        fetch_one("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {str(e)[:200]}"
        checks["ok"] = False
    # Redis
    try:
        from cache import get_redis
        r = get_redis()
        if r is not None:
            r.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "not_configured" if not os.environ.get("REDIS_URL") else "unavailable"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:200]}"
        checks["ok"] = False
    # Firebase
    try:
        from routers.internal import _ensure_firebase
        checks["firebase"] = "ok" if _ensure_firebase() else "not_configured"
    except Exception as e:
        checks["firebase"] = f"error: {str(e)[:200]}"
    from fastapi.responses import JSONResponse
    return JSONResponse(content=checks, status_code=200 if checks["ok"] else 503)

# Ownership boundary documented in models.py
