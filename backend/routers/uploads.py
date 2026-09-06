"""Upload endpoints: vault-validated staging for chat attachments."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend import schemas
from backend.deps import UserContext, current_user
from services.files import FileValidationError
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter
from services.storage import StorageError

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("", response_model=schemas.UploadMeta)
async def upload(file: UploadFile = File(...),
                 ctx: UserContext = Depends(current_user)):
    """Validate and vault one file; returns its attachment reference."""
    verdict = get_rate_limiter().check(ctx.user_id, "upload")
    if not verdict.allowed:
        obs_event("ratelimit.deny", action="upload", user=ctx.user_id,
                  retry_after_s=round(verdict.retry_after, 1))
        raise HTTPException(
            status_code=429,
            detail=f"Upload rate limit exceeded, retry in {verdict.retry_after:.0f}s.",
        )
    try:
        data: bytes = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read that file.")
    try:
        meta = ctx.file_store.save_upload(data, str(file.filename or "file"))
    except (FileValidationError, StorageError) as e:
        raise HTTPException(status_code=400, detail=f"Upload rejected: {e}")
    except Exception:
        raise HTTPException(status_code=400, detail="Upload rejected: unexpected storage error.")
    return {
        "id": meta.id,
        "kind": str(getattr(meta, "kind", "image") or "image"),
        "name": str(getattr(meta, "display_name", "file") or "file"),
    }


@router.get("", response_model=list[schemas.UploadMeta])
def list_uploads(ctx: UserContext = Depends(current_user)):
    """List the user's vaulted uploads."""
    try:
        metas = ctx.file_store.list_uploads()
    except (StorageError, FileValidationError):
        return []
    except Exception:
        return []
    out = []
    for meta in metas or []:
        try:
            out.append({
                "id": meta.id,
                "kind": str(getattr(meta, "kind", "image") or "image"),
                "name": str(getattr(meta, "display_name", "file") or "file"),
            })
        except Exception:
            continue
    return out


@router.get("/{upload_id}/file")
def download_upload(upload_id: str, ctx: UserContext = Depends(current_user)):
    """Download raw bytes of an owned upload (images render from here)."""
    try:
        meta = ctx.file_store.get_upload(upload_id)
    except (StorageError, FileValidationError):
        meta = None
    except Exception:
        meta = None
    if meta is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    try:
        path = ctx.file_store.resolve_upload(upload_id)
    except (StorageError, FileValidationError):
        path = None
    except Exception:
        path = None
    if path is None:
        raise HTTPException(status_code=404, detail="Upload file is unavailable.")
    name = str(getattr(meta, "display_name", "file") or "file")
    return FileResponse(str(path), filename=name)
