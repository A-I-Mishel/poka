"""Memory endpoints: notes text plus structured facts."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from backend import schemas
from backend.deps import UserContext, current_user
from services import memory as memory_svc
from services.storage import StorageError

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/notes")
def get_notes(ctx: UserContext = Depends(current_user)):
    """Read the user's memory notes."""
    try:
        return {"text": ctx.user_store.load_notes()}
    except StorageError:
        raise HTTPException(status_code=500, detail="Memory notes unavailable.")
    except Exception:
        raise HTTPException(status_code=500, detail="Memory notes unavailable.")


@router.put("/notes")
def save_notes(body: schemas.TextBody, ctx: UserContext = Depends(current_user)):
    """Save the user's memory notes."""
    try:
        ctx.user_store.save_notes(body.text)
    except StorageError:
        raise HTTPException(status_code=500, detail="Could not save memory notes.")
    except Exception:
        raise HTTPException(status_code=500, detail="Could not save memory notes.")
    return {"ok": True}


@router.get("/facts")
def list_facts(ctx: UserContext = Depends(current_user)):
    """List structured memory facts."""
    try:
        return memory_svc.list_memory_facts()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load memory facts.")


@router.delete("/facts")
def delete_fact(
    ctx: UserContext = Depends(current_user),
    ref: Optional[str] = Query(default=None),
    body: Optional[Dict[str, Any]] = Body(default=None),
):
    """Delete one structured fact by its reference (query param preferred)."""
    query = (ref or "").strip() or str(((body or {}).get("ref", ""))).strip()
    if not query:
        raise HTTPException(status_code=400, detail="Missing fact reference.")
    try:
        removed = memory_svc.delete_memory_fact(query)
    except Exception:
        removed = False
    if not removed:
        raise HTTPException(status_code=404, detail="Fact not found.")
    return {"ok": True}
