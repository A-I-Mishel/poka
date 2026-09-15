"""Generated-file (artifact) endpoints: list, download, regenerate, delete."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend import schemas
from backend.deps import UserContext, current_user
from services import research as research_svc
from services.files import FileValidationError
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter, rate_limit_headers
from services.storage import StorageError


def _check_generate_limit(ctx: UserContext) -> None:
    verdict = get_rate_limiter().check(ctx.limit_key or ctx.user_id, "generate")
    if not verdict.allowed:
        obs_event("ratelimit.deny", action="generate", user=ctx.user_id,
                  retry_after_s=round(verdict.retry_after, 1))
        raise HTTPException(
            status_code=429,
            detail=f"Generate rate limit exceeded, retry in {verdict.retry_after:.0f}s.",
            headers=rate_limit_headers(verdict, "generate"),
        )

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
    import re
    from urllib.parse import quote

    from services.limits import MAX_FILENAME_LEN

    # Sanitize for Content-Disposition (RFC 6266 + 5987): defense-in-depth,
    # legacy registry rows may contain unsanitized names.
    raw = str(name or artifact_id).replace("\x00", "").replace("\\", "_").replace("/", "_")
    raw = re.sub(r'[\x00-\x1f\x7f]', '', raw)
    raw = raw.replace('"', '').replace(";", "_").replace("\r", "").replace("\n", "").strip(" .")
    if not raw:
        raw = "file"
    if len(raw) > MAX_FILENAME_LEN:
        if "." in raw:
            base, ext = raw.rsplit(".", 1)
            ext = ext[:10]
            raw = base[: MAX_FILENAME_LEN - len(ext) - 1] + "." + ext
        else:
            raw = raw[:MAX_FILENAME_LEN]
    safe_name = raw
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
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": cd,
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.post("/{artifact_id}/regenerate", response_model=schemas.ArtifactMeta)
def regenerate_artifact(artifact_id: str, ctx: UserContext = Depends(current_user)):
    """Re-run the saved spec into a NEW artifact (original preserved)."""
    _check_generate_limit(ctx)
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
