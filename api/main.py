from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from routers import auth as auth_router
from routers import users as users_router
from routers import conferences as conf_router
from routers import bookmarks as bm_router
from routers import devices as dev_router
from routers import internal as internal_router

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Call4Paper API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    return {"ok": True}

# Ownership boundary documented in models.py
