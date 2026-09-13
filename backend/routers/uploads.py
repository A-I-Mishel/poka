"""Upload endpoints: vault-validated staging for chat attachments."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend import schemas
from backend.deps import UserContext, current_user
from services import kb as kb_svc
from services.files import FileValidationError
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter
from services.storage import StorageError

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("", response_model=schemas.UploadMeta)
async def upload(file: UploadFile = File(...),
                 ctx: UserContext = Depends(current_user)):
    """Validate and vault one file; returns its attachment reference."""
    from services.ratelimit import rate_limit_headers

    verdict = get_rate_limiter().check(ctx.limit_key or ctx.user_id, "upload")
    if not verdict.allowed:
        obs_event("ratelimit.deny", action="upload", user=ctx.user_id,
                  retry_after_s=round(verdict.retry_after, 1))
        raise HTTPException(
            status_code=429,
            detail=f"Upload rate limit exceeded, retry in {verdict.retry_after:.0f}s.",
            headers=rate_limit_headers(verdict, "upload"),
        )
    # Streamed read — never buffer more than MAX_UPLOAD_BYTES, chunk by chunk
    # to avoid 200 MB × concurrency OOM (previous await file.read() did).
    from services.limits import MAX_UPLOAD_BYTES

    # Early reject if client advertised a too-large Content-Length
    # (headers are untrusted but cheap to check before streaming).
    try:
        clen = file.size  # starlette UploadFile.size may be None or int
        if isinstance(clen, int) and clen > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum is {MAX_UPLOAD_BYTES // (1024*1024)} MB.",
            )
    except HTTPException:
        raise
    except Exception:
        pass
    try:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await file.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"File too large. Maximum is {MAX_UPLOAD_BYTES // (1024*1024)} MB.",
                )
            chunks.append(chunk)
            # Guard concurrent huge uploads — don't let one request hold >200 MB in RAM
            # via many chunks; already bounded by total above.
        data: bytes = b"".join(chunks) if len(chunks) > 1 else (chunks[0] if chunks else b"")
        if not data:
            # Let FileStore validate empty file with its user-safe message
            pass
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read that file.")
    try:
        meta = ctx.file_store.save_upload(data, str(file.filename or "file"))
    except (FileValidationError, StorageError) as e:
        raise HTTPException(status_code=400, detail=f"Upload rejected: {e}")
    except Exception:
        raise HTTPException(status_code=400, detail="Upload rejected: unexpected storage error.")
    # Best-effort knowledge-base ingest (never fails the upload):
    # text-bearing documents become vector-searchable for "what do my
    # documents say" questions. Images/unsupported types are skipped.
    try:
        kb_svc.ingest_document(ctx.user_id, meta.id, str(meta.display_name), data)
    except Exception:
        pass
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


@router.delete("/{upload_id}")
def delete_upload(upload_id: str, ctx: UserContext = Depends(current_user)):
    """Delete one owned upload (file + registry + KB vectors).

    Frees quota immediately. Referenced-by-chat uploads are removed
    anyway on explicit request: old message chips 404 gracefully and
    regenerating those turns fails loudly (400 unknown attachment).
    Unknown/unowned IDs 404 without revealing which (never raises).
    """
    try:
        removed = ctx.file_store.delete_upload(upload_id)
    except (StorageError, FileValidationError):
        removed = False
    except Exception:
        removed = False
    if not removed:
        raise HTTPException(status_code=404, detail="Upload not found.")
    # Best-effort KB forget (never fails the delete): pruned documents
    # must stop matching vector search without any other hook.
    try:
        kb_svc.drop_document(ctx.user_id, upload_id)
    except Exception:
        pass
    return {"ok": True}
