"""Ops endpoints: tier health snapshot + cooldown force-reset (authenticated)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.cascade import reset_tier_state, tier_status_snapshot
from backend.deps import UserContext, current_user
from services.obs import event as obs_event

router = APIRouter(prefix="/api/ops", tags=["ops"])


class ResetBody(BaseModel):
    tier: Optional[str] = None


@router.get("/tiers")
def tier_health(ctx: UserContext = Depends(current_user)):
    """Per-tier health: configured, cooldown remaining, streaks, last error."""
    try:
        return {"tiers": tier_status_snapshot()}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read tier state.")


@router.post("/tiers/reset")
def tier_reset(body: ResetBody, ctx: UserContext = Depends(current_user)):
    """Clear cooldown/failure state for one tier (or all when omitted)."""
    try:
        cleared = reset_tier_state(body.tier if body and body.tier else None)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not reset tier state.")
    try:
        obs_event("ops.tier_reset", user=ctx.user_id,
                  tier=str(body.tier) if body and body.tier else "all",
                  cleared=int(cleared))
    except Exception:
        pass
    return {"ok": True, "cleared": int(cleared)}
