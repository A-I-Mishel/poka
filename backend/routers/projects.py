"""Project endpoints: CRUD plus per-project context text."""

from fastapi import APIRouter, Depends, HTTPException

from backend import schemas
from backend.deps import UserContext, current_user
from services.storage import StorageError

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def list_projects(ctx: UserContext = Depends(current_user)):
    """List non-archived projects."""
    try:
        return ctx.user_store.list_projects()
    except StorageError as e:
        raise HTTPException(status_code=500, detail=f"Could not load projects: {e}")
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load projects.")


@router.post("", status_code=201)
def create_project(body: schemas.ProjectCreate,
                   ctx: UserContext = Depends(current_user)):
    """Create a project."""
    try:
        return ctx.user_store.create_project(body.name)
    except (ValueError, StorageError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not create project.")


@router.patch("/{project_id}")
def rename_project(project_id: str, body: schemas.ProjectRename,
                   ctx: UserContext = Depends(current_user)):
    """Rename a project."""
    try:
        renamed = ctx.user_store.rename_project(project_id, body.name)
    except (ValueError, StorageError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not rename project.")
    if not renamed:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"ok": True}


@router.post("/{project_id}/archive")
def archive_project(project_id: str, ctx: UserContext = Depends(current_user)):
    """Archive a project."""
    try:
        archived = ctx.user_store.archive_project(project_id)
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not archive project.")
    if not archived:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"ok": True}


@router.get("/{project_id}/context")
def get_context(project_id: str, ctx: UserContext = Depends(current_user)):
    """Read a project's context text."""
    try:
        return {"text": ctx.user_store.load_project_context(project_id)}
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load project context.")


@router.put("/{project_id}/context")
def save_context(project_id: str, body: schemas.TextBody,
                 ctx: UserContext = Depends(current_user)):
    """Save a project's context text (exact bytes)."""
    try:
        ctx.user_store.save_project_context(project_id, body.text)
    except (ValueError, StorageError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not save project context.")
    return {"ok": True}


@router.get("/{project_id}/briefs")
def project_briefs(project_id: str, ctx: UserContext = Depends(current_user)):
    """List briefs filed under a project."""
    try:
        return ctx.user_store.list_briefs(project_id=project_id)
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load briefs.")
