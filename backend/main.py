"""Pluto API: FastAPI backend reusing the agent/services stack directly.

Run (from the repo root)::

    uvicorn backend.main:app --port 8000

The vanilla-JS frontend (frontend/) talks to this API.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.secrets import get_secret

load_dotenv()

from backend.routers import approvals, artifacts, auth, briefs, chat, chats, export, memory, meta, observability, ops, projects, uploads, workflows  # noqa: E402

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    from services.identity import auth_mode as _auth_mode

    _mode = _auth_mode()
    if _mode == "private":
        _tokens = (get_secret("PLUTO_ACCESS_TOKENS", "") or "").strip()
        if not _tokens:
            # Accounts (username/password) can still admit users — don't
            # fail fast here (would break private+accounts deploys).
            # secrets.validate_secrets() already warns loudly.
            logger.warning(
                "PLUTO_AUTH_MODE=private without PLUTO_ACCESS_TOKENS — "
                "token login disabled; accounts/sessions still work."
            )
    if _mode == "open":
        logger.warning(
            "PLUTO_AUTH_MODE=open — unauthenticated access enabled. "
            "Public deployments must set PLUTO_AUTH_MODE=private and "
            "PLUTO_ACCESS_TOKENS."
        )
        # Fail-closed on public hosts: open mode is for localhost/dev only.
        # Operators who truly want a public open instance must opt in via
        # PLUTO_ALLOW_OPEN=true (documented footgun, never the default).
        try:
            _allow_open = (get_secret("PLUTO_ALLOW_OPEN", "") or "").strip().lower() in (
                "1", "true", "yes", "on",
            )
            _on_hosted = bool((get_secret("PORT", "") or "").strip()
                              or (get_secret("RENDER", "") or "").strip())
            _origin = (get_secret("PLUTO_FRONTEND_ORIGIN", "") or "").strip()
            _public_origin = bool(_origin) and not any(
                h in _origin for h in ("localhost", "127.0.0.1", "[::1]")
            )
            if (_on_hosted or _public_origin) and not _allow_open:
                raise RuntimeError(
                    "Refusing to start PLUTO_AUTH_MODE=open on a public host "
                    "(PORT/RENDER set or non-localhost PLUTO_FRONTEND_ORIGIN). "
                    "Set PLUTO_AUTH_MODE=private + PLUTO_ACCESS_TOKENS, or "
                    "explicitly opt in with PLUTO_ALLOW_OPEN=true for a "
                    "public demo."
                )
        except RuntimeError:
            raise
        except Exception:
            logger.warning("public-host open-mode check failed; failing closed", exc_info=True)
            raise RuntimeError("Startup safety check failed; refusing to start open mode.")
        try:
            if (get_secret("PLUTO_USER_ID", "") or "").strip():
                _allow_shared = (get_secret("PLUTO_ALLOW_SHARED_VAULT", "") or "").strip().lower() in (
                    "1", "true", "yes", "on",
                )
                if not _allow_shared:
                    # Shared vault in open mode on a public host silently
                    # merges every logged-out visitor into one vault.
                    _origin2 = (get_secret("PLUTO_FRONTEND_ORIGIN", "") or "").strip()
                    _hosted2 = bool((get_secret("PORT", "") or "").strip()
                                    or (get_secret("RENDER", "") or "").strip())
                    _public2 = bool(_origin2) and not any(
                        h in _origin2 for h in ("localhost", "127.0.0.1", "[::1]")
                    )
                    if _hosted2 or _public2:
                        raise RuntimeError(
                            "PLUTO_USER_ID is set while PLUTO_AUTH_MODE=open on a "
                            "public host — every logged-out visitor would share "
                            "that vault. Unset PLUTO_USER_ID or opt in with "
                            "PLUTO_ALLOW_SHARED_VAULT=true."
                        )
                logger.warning(
                    "PLUTO_USER_ID is set while PLUTO_AUTH_MODE=open — "
                    "every logged-out visitor without a Bearer token shares "
                    "that vault. Unset PLUTO_USER_ID on shared hosts."
                )
        except RuntimeError:
            raise
        except Exception:
            logger.warning("shared-vault open-mode check failed; failing closed", exc_info=True)
            raise RuntimeError("Startup safety check failed; refusing to start open mode.")
    try:
        _workers = int(get_secret("UVICORN_WORKERS", "1") or "1")
    except (TypeError, ValueError):
        _workers = 1
    if _workers > 1:
        logger.warning(
            "UVICORN_WORKERS=%d — rate limits and locks are per-process "
            "best-effort; use a single worker or external Redis limiter "
            "for hard abuse/billing enforcement.",
            _workers,
        )
        _allow_mem = (get_secret("PLUTO_ALLOW_MEMORY_LIMITER", "") or "").strip().lower() in (
            "1", "true", "yes", "on",
        )
        if not (get_secret("REDIS_URL", "") or "").strip() and not _allow_mem:
            raise RuntimeError(
                "UVICORN_WORKERS>1 without REDIS_URL uses per-process "
                "in-memory rate limits (over-blocks NAT, under-blocks "
                "distributed abuse). Set REDIS_URL or explicitly opt in "
                "with PLUTO_ALLOW_MEMORY_LIMITER=true for local dev."
            )
        if _mode == "private" and not (get_secret("REDIS_URL", "") or "").strip():
            raise RuntimeError(
                "PLUTO_AUTH_MODE=private with UVICORN_WORKERS>1 requires REDIS_URL "
                "for distributed rate limiting (abuse/billing enforcement)."
            )
    # Behind Render/Vercel the client IP arrives via X-Forwarded-For.
    # Without PLUTO_TRUST_PROXY=true limits key on the proxy peer IP,
    # collapsing all visitors into one bucket (over-blocking).
    try:
        _trust = (get_secret("PLUTO_TRUST_PROXY", "false") or "false").strip().lower() in (
            "1", "true", "yes", "on",
        )
        if not _trust and (get_secret("PORT", "") or get_secret("RENDER", "")):
            logger.warning(
                "PLUTO_TRUST_PROXY is false behind a proxy (PORT/RENDER set) — "
                "rate limits will key on proxy IP. Set PLUTO_TRUST_PROXY=true "
                "when behind a trusted proxy."
            )
    except Exception:
        logger.debug("trust-proxy check failed", exc_info=True)
    # Tracing: best-effort, never blocks startup (NoOp when unconfigured).
    try:
        from services.tracing import init_tracing as _init_tracing

        _init_tracing()
    except Exception:
        logger.warning("tracing init skipped", exc_info=True)
    # validate secrets placeholders (never logs values)
    try:
        from services.secrets import validate_secrets

        for w in validate_secrets():
            logger.warning(w)
    except Exception:
        logger.debug("secret validation failed", exc_info=True)
    # Free-tier durability: restore data/ from the R2 snapshot when the
    # local disk is empty (Render free wipes it on every restart). Skipped
    # when R2 is unconfigured or local data exists; never blocks startup.
    try:
        from services.snapshots import maybe_restore as _maybe_restore

        _maybe_restore()
    except Exception:
        logger.warning("snapshot restore skipped", exc_info=True)
    # Start background scheduler for storage hygiene
    try:
        from services.scheduler import start_scheduler as _start_scheduler

        _start_scheduler()
    except Exception:
        logger.warning("background scheduler failed to start", exc_info=True)
    # Pre-warm tokenizer for faster first request
    try:
        from services.tokens import prewarm_tokenizer as _prewarm_tokenizer

        _prewarm_tokenizer()
    except Exception:
        logger.warning("tokenizer prewarm failed", exc_info=True)
    # Auto-configure Redis rate limiter if REDIS_URL is set.
    # In private mode a configured-but-unreachable Redis fails fast
    # (fail-closed for abuse/billing); in open mode we fall back to
    # in-memory with a warning (local dev convenience).
    try:
        from services.ratelimit_redis import create_redis_limiter as _create_redis_limiter
        from services.ratelimit import configure_rate_limiter as _configure_rate_limiter

        _redis_url = (get_secret("REDIS_URL", "") or "").strip()
        redis_limiter = _create_redis_limiter()
        if redis_limiter is not None:
            # Smoke-test the connection so a dead Redis never silently
            # degrades to per-process limits in private mode.
            try:
                redis_limiter.check("__startup__", "chat")
                try:
                    redis_limiter.reset("__startup__")
                except Exception:
                    logger.debug("startup probe reset failed", exc_info=True)
            except Exception as _e:
                if _mode == "private":
                    raise RuntimeError(f"REDIS_URL unreachable in private mode: {_e}") from _e
                raise
            _configure_rate_limiter(redis_limiter)
            logger.info("Redis rate limiter enabled")
        elif _redis_url and _mode == "private":
            raise RuntimeError("REDIS_URL is set but Redis limiter init returned None in private mode.")
    except RuntimeError:
        raise
    except Exception:
        logger.warning("Redis rate limiter init failed, using in-memory limiter", exc_info=True)
    yield
    # Flush any pending backup before shutdown.
    try:
        from services.snapshots import flush as _snapshots_flush

        _snapshots_flush()
    except Exception:
        logger.warning("snapshot flush on shutdown failed", exc_info=True)
    # Stop background scheduler
    try:
        from services.scheduler import stop_scheduler as _stop_scheduler

        _stop_scheduler()
    except Exception:
        logger.warning("background scheduler stop failed", exc_info=True)


# Hide interactive docs + schema in private mode (prevents unauthenticated schema leakage).
_is_private = (get_secret("PLUTO_AUTH_MODE", "open") or "open").strip().lower() == "private"
app = FastAPI(
    title="Pluto API",
    version="0.1.0",
    lifespan=_lifespan,
    docs_url=None if _is_private else "/docs",
    redoc_url=None if _is_private else "/redoc",
    openapi_url=None if _is_private else "/openapi.json",
)

# --- CORS hardening -------------------------------------------------
# Explicit allow-list, validated origins — never "*" with credentials.
# Private mode is fail-closed: PLUTO_FRONTEND_ORIGIN must be set
# explicitly (no localhost fallback on public hosts). Open mode keeps
# the localhost fallback for local dev convenience.
import re as _cors_re

_VALID_ORIGIN_RE = _cors_re.compile(r"^https?://[^/\s]+$")

_raw_origins = get_secret("PLUTO_FRONTEND_ORIGIN", "") or ""
if not _raw_origins.strip() and not _is_private:
    _raw_origins = "http://localhost:5173"
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
    if _is_private:
        raise RuntimeError(
            "PLUTO_AUTH_MODE=private requires PLUTO_FRONTEND_ORIGIN "
            "(e.g. https://app.example.com). Refusing to start with an open/localhost fallback."
        )
    logger.warning("No valid PLUTO_FRONTEND_ORIGIN — falling back to http://localhost:5173")
    _frontend_origins = ["http://localhost:5173"]

_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
# Note: X-Forwarded-For is intentionally NOT allowlisted. Browsers must
# never spoof it (rate-limit bypass when PLUTO_TRUST_PROXY=true);
# proxies add it outside CORS, and the server still reads it.
_ALLOWED_HEADERS = ["Authorization", "Content-Type", "X-Pluto-Visitor", "X-Request-Id", "X-Pluto-Csrf"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_credentials=True,
    allow_methods=_ALLOWED_METHODS,
    allow_headers=_ALLOWED_HEADERS,
)


# --- Security headers -------------------------------------------------
# API + same-origin file downloads: never let user-controlled bytes
# execute in the UI origin. Downloads force attachment + nosniff +
# sandbox at the endpoint; this middleware adds the baseline for
# every response (JSON included).
@app.middleware("http")
async def _security_headers(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    return response

# Optional host-header validation (set PLUTO_TRUSTED_HOSTS="api.example.com,*.example.com")
_trusted_hosts_raw = (get_secret("PLUTO_TRUSTED_HOSTS", "") or "").strip()
if _trusted_hosts_raw:
    from fastapi.middleware.trustedhost import TrustedHostMiddleware

    _trusted_hosts = [h.strip() for h in _trusted_hosts_raw.split(",") if h.strip()]
    if _trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts)
        logger.info("TrustedHostMiddleware enabled for %s", _trusted_hosts)

# Request observability (outermost: times the full stack, echoes
# X-Request-Id on every response, feeds Prometheus + access logs).
# Added last so it wraps CORS/security-host handling too.
from backend.middleware.observability import ObservabilityMiddleware  # noqa: E402

app.add_middleware(ObservabilityMiddleware)

for _router in (
    approvals.router,
    auth.router,
    chat.router,
    chats.router,
    export.router,
    uploads.router,
    artifacts.router,
    projects.router,
    briefs.router,
    workflows.router,
    memory.router,
    meta.router,
    observability.router,
    ops.router,
):
    app.include_router(_router)


@app.get("/api")
def root():
    """API index (the UI is served separately in development)."""
    return {"ok": True, "name": "Pluto API", "docs": None if _is_private else "/docs"}


@app.get("/api/{_rest:path}")
def _api_fallback(_rest: str):
    """Guarantee JSON 404 for unknown /api/* paths (StaticFiles would 200 index.html)."""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=404, content={"detail": "Not found."})


# Single-server demo mode: when frontend/dist exists, serve it.
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
