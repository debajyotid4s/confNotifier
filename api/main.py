"""Call4Paper API — application wiring.

Read paths are cache-first and anonymous; write paths require a JWT. See
models.py for the scraper/API table ownership boundary.
"""

import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from routers import auth as auth_router
from routers import bookmarks as bm_router
from routers import conferences as conf_router
from routers import devices as dev_router
from routers import internal as internal_router
from routers import users as users_router

# Guard against a second basicConfig when the app is imported by tests.
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

#: Conference payloads are highly compressible JSON; the Android client sends
#: Accept-Encoding: gzip, so this cuts mobile transfer substantially.
GZIP_MIN_SIZE = 512

#: Headers applied to every response. The API serves JSON to a native client, so
#: it should never be treated as a document by a browser.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


def _cors_origins() -> list[str]:
    """Allowed browser origins.

    Defaults to production only: localhost was previously in the default list, so
    an unset CORS_ORIGINS shipped a dev origin to production. Add local origins
    explicitly via the env var when developing.
    """
    raw = os.environ.get("CORS_ORIGINS", "https://confnotifier.onrender.com")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Warm the connection pool and Firebase before the first request.

    Render's free tier cold-starts often; paying the pool handshake and the
    Firebase credential parse during startup keeps it off the first user request.
    """
    try:
        from database import fetch_one

        fetch_one("SELECT 1")
        logger.info("startup: database reachable")
    except Exception as e:
        logger.warning("startup: database warm-up failed: %s", e)

    try:
        from routers.internal import _ensure_firebase

        logger.info("startup: firebase %s",
                    "ready" if _ensure_firebase() else "not configured")
    except Exception as e:
        logger.warning("startup: firebase warm-up failed: %s", e)

    yield


app = FastAPI(title="Call4Paper API", version="0.3.0", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_SIZE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Notify-Secret"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(conf_router.router)
app.include_router(bm_router.router)
app.include_router(dev_router.router)
app.include_router(internal_router.router)


@app.get("/health")
def health(request: Request):
    """Liveness probe.

    Returns only `{"ok": ...}` to anonymous callers: the previous version exposed
    which backing services were down, which is useful reconnaissance. The
    per-dependency breakdown is returned only when the internal secret is
    supplied, so the Docker healthcheck and operators can still see detail.
    """
    checks = {"ok": True}

    try:
        from database import fetch_one

        fetch_one("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        logger.warning("health: db check failed: %s", e)
        checks["db"] = "error"
        checks["ok"] = False

    try:
        from cache import get_redis, _is_redis_configured

        redis = get_redis()
        if redis is not None:
            redis.ping()
            checks["redis"] = "ok"
        else:
            # Redis is optional: absent is fine, configured-but-down is degraded
            # but not fatal, because caching and rate limiting fail open.
            checks["redis"] = "unavailable" if _is_redis_configured() else "not_configured"
    except Exception as e:
        logger.warning("health: redis check failed: %s", e)
        checks["redis"] = "error"

    expected = os.environ.get("NOTIFY_SECRET", "")
    supplied = request.headers.get("x-notify-secret", "")
    detailed = bool(expected) and bool(supplied) and hmac.compare_digest(supplied, expected)

    status_code = 200 if checks["ok"] else 503
    body = checks if detailed else {"ok": checks["ok"]}
    return JSONResponse(content=body, status_code=status_code)
