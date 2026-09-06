"""Meta endpoints: health and configured model tiers."""

from fastapi import APIRouter, Depends

from backend import schemas
from backend.deps import UserContext, current_user
from services.identity import auth_mode

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health", response_model=schemas.HealthResponse)
def health(ctx: UserContext = Depends(current_user)):
    """Liveness plus the tiers actually configured with keys."""
    from config import TIER_GETTERS

    configured = []
    for name, getter in TIER_GETTERS:
        try:
            if getter() is not None:
                configured.append(name)
        except Exception:
            continue
    return {"ok": True, "tiers": configured, "auth_mode": auth_mode()}


@router.get("/tiers")
def tiers(ctx: UserContext = Depends(current_user)):
    """Names of all known tiers in cascade order (configured or not)."""
    from config import TIER_GETTERS

    return {"tiers": [name for name, _getter in TIER_GETTERS]}
