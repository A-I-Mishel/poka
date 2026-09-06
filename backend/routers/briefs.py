"""Research-brief endpoints: list, save-from-message, docx, delete."""

from fastapi import APIRouter, Depends, HTTPException

from backend import schemas
from backend.deps import UserContext, current_user
from services import research as research_svc
from services.storage import StorageError

router = APIRouter(prefix="/api/briefs", tags=["briefs"])


@router.get("")
def list_briefs(ctx: UserContext = Depends(current_user)):
    """List all briefs (newest first)."""
    try:
        return ctx.user_store.list_briefs()
    except StorageError as e:
        raise HTTPException(status_code=500, detail=f"Could not load briefs: {e}")
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load briefs.")


@router.post("", status_code=201)
def save_brief(body: schemas.BriefFromMessage,
               ctx: UserContext = Depends(current_user)):
    """Save a search-backed assistant message from the open chat as a brief."""
    try:
        stored, _warnings = ctx.user_store.load_chats()
    except StorageError:
        stored = {"chats": [], "current": []}
    messages = stored.get("current", []) if isinstance(stored, dict) else []
    if not isinstance(messages, list):
        messages = []
    try:
        record = research_svc.create_brief_from_message(
            ctx.user_store, messages, int(body.index), body.project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not save brief.")
    return record


@router.post("/{brief_id}/docx")
def brief_docx(brief_id: str, ctx: UserContext = Depends(current_user)):
    """Generate a Word document from a brief (registers a new artifact)."""
    try:
        new_meta = research_svc.generate_docx_from_brief(
            ctx.user_store, ctx.file_store, brief_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not generate document.")
    return {
        "id": str(new_meta.id),
        "kind": str(new_meta.kind),
        "name": str(new_meta.display_name),
    }


@router.delete("/{brief_id}")
def delete_brief(brief_id: str, ctx: UserContext = Depends(current_user)):
    """Delete a brief."""
    try:
        removed = ctx.user_store.delete_brief(brief_id)
    except StorageError:
        removed = False
    except Exception:
        removed = False
    if not removed:
        raise HTTPException(status_code=404, detail="Brief not found.")
    return {"ok": True}
