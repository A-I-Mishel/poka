"""Generated-file (artifact) endpoints: list, download, regenerate, delete."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend import schemas
from backend.deps import UserContext, current_user
from services import research as research_svc
from services.files import FileValidationError
from services.storage import StorageError

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("", response_model=List[schemas.ArtifactMeta])
def list_artifacts(ctx: UserContext = Depends(current_user)):
    """List generated outputs, newest first."""
    try:
        metas = ctx.file_store.list_outputs()
    except (StorageError, FileValidationError):
        return []
    except Exception:
        return []
    out = []
    for meta in metas or []:
        try:
            out.append({
                "id": str(meta.id),
                "kind": str(meta.kind),
                "name": str(meta.display_name),
                "sub": "",
            })
        except Exception:
            continue
    return out


@router.get("/{artifact_id}/download")
def download_artifact(artifact_id: str, ctx: UserContext = Depends(current_user)):
    """Download one generated file."""
    try:
        data = ctx.file_store.read_output(artifact_id)
    except StorageError:
        data = None
    except Exception:
        data = None
    if data is None:
        raise HTTPException(status_code=404, detail="Artifact expired or not found.")
    try:
        meta = ctx.file_store.get_output(artifact_id)
        name = str(meta.display_name) if meta else artifact_id
    except StorageError:
        name = artifact_id
    except Exception:
        name = artifact_id
    from fastapi.responses import Response

    media = "application/octet-stream"
    lowered = name.lower()
    if lowered.endswith(".pptx"):
        media = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    elif lowered.endswith(".docx"):
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/{artifact_id}/regenerate", response_model=schemas.ArtifactMeta)
def regenerate_artifact(artifact_id: str, ctx: UserContext = Depends(current_user)):
    """Re-run the saved spec into a NEW artifact (original preserved)."""
    try:
        eligible = research_svc.can_regenerate(ctx.file_store, artifact_id)
    except Exception:
        eligible = False
    if not eligible:
        raise HTTPException(
            status_code=400,
            detail="This file cannot be regenerated (no saved settings).")
    try:
        new_meta = research_svc.regenerate_artifact(ctx.file_store, artifact_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not regenerate this file.")
    return {
        "id": str(new_meta.id),
        "kind": str(new_meta.kind),
        "name": str(new_meta.display_name),
        "sub": "",
    }


@router.delete("/{artifact_id}")
def delete_artifact(artifact_id: str, ctx: UserContext = Depends(current_user)):
    """Delete one generated file."""
    try:
        removed = ctx.file_store.delete_output(artifact_id)
    except (StorageError, FileValidationError):
        removed = False
    except Exception:
        removed = False
    if not removed:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return {"ok": True}


@router.delete("")
def delete_all_artifacts(ctx: UserContext = Depends(current_user)):
    """Delete all generated files."""
    try:
        count = ctx.file_store.delete_all_outputs()
    except (StorageError, FileValidationError):
        count = 0
    except Exception:
        count = 0
    return {"ok": True, "deleted": int(count)}
