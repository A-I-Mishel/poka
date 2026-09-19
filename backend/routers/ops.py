"""Ops endpoints: tier health snapshot + cooldown force-reset (authenticated)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.cascade import reset_tier_state, tier_status_snapshot
from backend.deps import UserContext, current_user
from services.obs import event as obs_event

logger: logging.Logger = logging.getLogger(__name__)

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


@router.get("/router")
def router_stats(limit: int = 50, ctx: UserContext = Depends(current_user)):
    """Deterministic router stats + scrubbed fallthrough patterns (no PII).

    Use top patterns to grow services/normalize.py synonyms — never add
    ad-hoc keyword branches. Limit clamped 1..200.
    """
    try:
        from agent.cascade import ROUTER_STATS
        from agent.router import get_fallthrough_stats

        try:
            lim = max(1, min(200, int(limit)))
        except Exception:
            lim = 50
        stats = get_fallthrough_stats(limit=lim)
        return {"router": dict(ROUTER_STATS), "fallthrough": stats}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read router stats.")


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
        logger.debug("obs_event tier_reset failed", exc_info=True)
    return {"ok": True, "cleared": int(cleared)}
