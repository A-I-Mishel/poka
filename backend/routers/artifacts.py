"""Generated-file (artifact) endpoints: list, download, regenerate, delete."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend import schemas
from backend.deps import UserContext, check_generate_limit, current_user
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
    """Download one generated file (streamed, not full-RAM)."""
    try:
        meta = ctx.file_store.get_output(artifact_id)
    except StorageError:
        meta = None
    except Exception:
        meta = None
    if meta is None:
        raise HTTPException(status_code=404, detail="Artifact expired or not found.")
    # Resolve path without reading bytes into RAM (artifacts up to 50MB)
    candidate = ctx.file_store.outputs_dir / getattr(meta, "stored_name", "")
    try:
        if not ctx.file_store._inside(ctx.file_store.outputs_dir, candidate) or not candidate.is_file():
            raise HTTPException(status_code=404, detail="Artifact expired or not found.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Artifact expired or not found.")
    name = str(getattr(meta, "display_name", artifact_id) or artifact_id)
    from fastapi.responses import FileResponse
    from urllib.parse import quote

    from services.files import sanitize_download_filename

    # Sanitize for Content-Disposition (RFC 6266 + 5987): defense-in-depth,
    # legacy registry rows may contain unsanitized names.
    safe_name = sanitize_download_filename(name or artifact_id)
    media = "application/octet-stream"
    lowered = safe_name.lower()
    if lowered.endswith(".pptx"):
        media = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    elif lowered.endswith(".docx"):
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif lowered.endswith(".pdf"):
        media = "application/pdf"
    elif lowered.endswith(".md"):
        media = "text/markdown"
    elif lowered.endswith(".doc"):
        media = "application/msword"
    elif lowered.endswith((".html", ".htm")):
        # Generated HTML pages are downloadable artifacts: force inert
        # bytes so opening the link downloads instead of executing
        # script in the API/UI origin.
        media = "application/octet-stream"
    # RFC 5987: ascii fallback + encoded utf-8 for non-ascii
    ascii_fb = safe_name.encode("ascii", "replace").decode("ascii").replace("?", "_")
    if ascii_fb != safe_name or any(ord(c) > 127 for c in safe_name):
        quoted = quote(safe_name, safe="!#$&+-.^_`|~")
        cd = f'attachment; filename="{ascii_fb}"; filename*=UTF-8\'\'{quoted}'
    else:
        cd = f'attachment; filename="{safe_name}"'
    return FileResponse(
        str(candidate),
        media_type=media,
        filename=safe_name,
        headers={
            "Content-Disposition": cd,
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.post("/{artifact_id}/regenerate", response_model=schemas.ArtifactMeta)
def regenerate_artifact(artifact_id: str, ctx: UserContext = Depends(current_user)):
    """Re-run the saved spec into a NEW artifact (original preserved)."""
    check_generate_limit(ctx)
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
