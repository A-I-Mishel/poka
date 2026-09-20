"""Self-improvement audit: learned lessons (authenticated, per-user).

Lists what Pluto learned from this user's task episodes (lesson id,
task shape, tool sequence, support/oppose counts, status) and allows
disabling bad lessons. Lessons never contain prompts, keys, file
bytes, or user data — only task types and allowlisted tool names.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.deps import UserContext, current_user
from services.obs import event as obs_event

logger: logging.Logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


@router.get("")
def list_lessons(ctx: UserContext = Depends(current_user)):
    """Learned lessons with evidence counts and status."""
    try:
        from services.experience import get_lessons

        return {"lessons": get_lessons(ctx.user_id)}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read lessons.")


@router.delete("/{lesson_id}")
def disable_lesson(lesson_id: str, ctx: UserContext = Depends(current_user)):
    """Permanently disable a lesson (never auto re-enabled)."""
    try:
        from services.experience import disable_lesson as _disable

        ok = _disable(ctx.user_id, lesson_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not disable lesson.")
    if not ok:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    try:
        obs_event("ops.lesson_disable", user=ctx.user_id, lesson=str(lesson_id))
    except Exception:
        logger.debug("obs_event lesson_disable failed", exc_info=True)
    return {"ok": True}
