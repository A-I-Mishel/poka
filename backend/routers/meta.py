"""Meta endpoints: health and configured model tiers."""

import logging
import threading
import time

from fastapi import APIRouter, Depends

from backend import schemas
from backend.deps import UserContext, current_user
from services.identity import auth_mode
from services.secrets import get_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["meta"])

# Cached live-tier probe: probing every /health would burn quota and
# add up to PROBE_TIMEOUT_SECONDS latency to orchestrator checks.
# Cache for 60s; failures cache as None (still report configured tiers).
# Single-flight (Finding 5): the lock previously covered only the cache
# check, so every concurrent request after expiry fired its own provider
# probe (quota burn x N). Now the first request becomes the prover while
# the rest get the stale tier immediately (stale-while-revalidate —
# health never blocks behind a slow provider).
_live_cache_lock = threading.Lock()
_live_cache: dict = {"at": 0.0, "tier": None, "probing": False}


def _cached_live_tier(configured: list) -> object:
    if not configured:
        return None
    # Opt-out for cold-boot speed / quota: PLUTO_HEALTH_PROBE=0 disables
    # the live network probe (liveness only, no readiness).
    try:
        if (get_secret("PLUTO_HEALTH_PROBE", "1") or "1").strip().lower() in (
            "0", "false", "no", "off",
        ):
            return None
    except Exception:
        logger.debug("health probe flag parse failed", exc_info=True)
    now = time.time()
    with _live_cache_lock:
        if now - float(_live_cache.get("at", 0.0)) < 60.0:
            return _live_cache.get("tier")
        if _live_cache.get("probing"):
            # A probe is already in flight: serve stale immediately.
            return _live_cache.get("tier")
        _live_cache["probing"] = True
    tier = None
    try:
        from agent.runtime import probe_live_tier as _probe
        from services.limits import PROBE_TIMEOUT_SECONDS as _timeout

        tier = _probe(timeout=float(_timeout))
    except Exception:
        logger.debug("live tier probe failed", exc_info=True)
        tier = None
    with _live_cache_lock:
        _live_cache["at"] = time.time()
        _live_cache["tier"] = tier
        _live_cache["probing"] = False
    return tier


@router.get("/health", response_model=schemas.HealthResponse)
def health():
    """Liveness plus the tiers actually configured with keys.

    Public — no authentication required so container orchestrators
    (Render, Kubernetes, Docker HEALTHCHECK) can probe it. Private
    mode is still reported via `auth_mode` so operators can verify.
    Live-tier probe is cached 60s and never blocks liveness: orchestrators
    get ok=True even when all tiers are down (readiness signal is
    `live_tier is not None` + `tiers` non-empty).
    """
    from config import TIER_GETTERS

    configured = []
    for name, getter in TIER_GETTERS:
        try:
            if getter() is not None:
                configured.append(name)
        except Exception:
            logger.debug("tier probe failed for %s", name, exc_info=True)
            continue
    mode = auth_mode()
    if mode == "open":
        logger.debug("health probed in open mode — not suitable for public deploys")
    try:
        from services.ratelimit import get_rate_limiter as _get_limiter

        limiter_name = type(_get_limiter()).__name__.replace("RateLimiter", "").lower() or "memory"
        if "redis" in type(_get_limiter()).__name__.lower():
            limiter_name = "redis"
        elif "memory" in type(_get_limiter()).__name__.lower():
            limiter_name = "memory"
    except Exception:
        logger.debug("rate limiter name probe failed", exc_info=True)
        limiter_name = "memory"
    try:
        from services.snapshots import configured as _snap_configured

        snaps = bool(_snap_configured())
    except Exception:
        logger.debug("snapshot configured probe failed", exc_info=True)
        snaps = False
    return {
        "ok": True,
        "tiers": configured,
        "auth_mode": mode,
        "live_tier": _cached_live_tier(configured),
        "limiter": limiter_name,
        "snapshots_configured": snaps,
    }


@router.get("/tiers")
def tiers(ctx: UserContext = Depends(current_user)):
    """Names of all known tiers in cascade order (configured or not)."""
    from config import TIER_GETTERS

    return {"tiers": [name for name, _getter in TIER_GETTERS]}
