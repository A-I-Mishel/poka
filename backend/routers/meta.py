"""Meta endpoints: health and configured model tiers."""

import logging

from fastapi import APIRouter, Depends

from backend import schemas
from backend.deps import UserContext, current_user
from services.identity import auth_mode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health", response_model=schemas.HealthResponse)
def health():
    """Liveness plus the tiers actually configured with keys.

    Public — no authentication required so container orchestrators
    (Render, Kubernetes, Docker HEALTHCHECK) can probe it. Private
    mode is still reported via `auth_mode` so operators can verify.
    """
    from config import TIER_GETTERS

    configured = []
    for name, getter in TIER_GETTERS:
        try:
            if getter() is not None:
                configured.append(name)
        except Exception:
            continue
    mode = auth_mode()
    if mode == "open":
        logger.debug("health probed in open mode — not suitable for public deploys")
    return {"ok": True, "tiers": configured, "auth_mode": mode}


@router.get("/tiers")
def tiers(ctx: UserContext = Depends(current_user)):
    """Names of all known tiers in cascade order (configured or not)."""
    from config import TIER_GETTERS

    return {"tiers": [name for name, _getter in TIER_GETTERS]}
