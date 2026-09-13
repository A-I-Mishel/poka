"""Pluto API: FastAPI backend reusing the agent/services stack directly.

Run (from the repo root)::

    uvicorn backend.main:app --port 8000

The vanilla-JS frontend (frontend/) talks to this API.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from backend.routers import artifacts, auth, briefs, chat, chats, memory, meta, projects, uploads, workflows  # noqa: E402

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    from services.identity import auth_mode as _auth_mode

    if _auth_mode() == "open":
        logger.warning(
            "PLUTO_AUTH_MODE=open — unauthenticated access enabled. "
            "Public deployments must set PLUTO_AUTH_MODE=private and "
            "PLUTO_ACCESS_TOKENS."
        )
    # validate secrets placeholders (never logs values)
    try:
        from services.secrets import validate_secrets

        for w in validate_secrets():
            logger.warning(w)
    except Exception:
        pass
    yield


app = FastAPI(title="Pluto API", version="0.1.0", lifespan=_lifespan)

# --- CORS hardening -------------------------------------------------
# Explicit allow-list, validated origins — never "*" with credentials.
# Empty or invalid list falls back to localhost:5173 with a warning.
import re as _cors_re

_VALID_ORIGIN_RE = _cors_re.compile(r"^https?://[^/\s]+$")

_raw_origins = os.getenv("PLUTO_FRONTEND_ORIGIN", "http://localhost:5173")
_frontend_origins: list[str] = []
for _o in _raw_origins.split(","):
    _o = _o.strip().rstrip("/")
    if not _o:
        continue
    if _o == "*" or "*" in _o:
        logger.warning("CORS origin '*' rejected with allow_credentials=True; ignoring")
        continue
    if not _VALID_ORIGIN_RE.match(_o):
        logger.warning("CORS origin %r invalid (must be http(s)://host); ignoring", _o)
        continue
    _frontend_origins.append(_o)
if not _frontend_origins:
    logger.warning("No valid PLUTO_FRONTEND_ORIGIN — falling back to http://localhost:5173")
    _frontend_origins = ["http://localhost:5173"]

_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_ALLOWED_HEADERS = ["Authorization", "Content-Type", "X-Pluto-Visitor", "X-Forwarded-For", "X-Request-Id"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_credentials=True,
    allow_methods=_ALLOWED_METHODS,
    allow_headers=_ALLOWED_HEADERS,
)

# Optional host-header validation (set PLUTO_TRUSTED_HOSTS="api.example.com,*.example.com")
_trusted_hosts_raw = os.getenv("PLUTO_TRUSTED_HOSTS", "").strip()
if _trusted_hosts_raw:
    from fastapi.middleware.trustedhost import TrustedHostMiddleware

    _trusted_hosts = [h.strip() for h in _trusted_hosts_raw.split(",") if h.strip()]
    if _trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts)
        logger.info("TrustedHostMiddleware enabled for %s", _trusted_hosts)

for _router in (
    auth.router,
    chat.router,
    chats.router,
    uploads.router,
    artifacts.router,
    projects.router,
    briefs.router,
    workflows.router,
    memory.router,
    meta.router,
):
    app.include_router(_router)


@app.get("/api")
def root():
    """API index (the UI is served separately in development)."""
    return {"ok": True, "name": "Pluto API", "docs": "/docs"}


# Single-server demo mode: when frontend/dist exists, serve it.
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
