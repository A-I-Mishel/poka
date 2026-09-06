"""Chat send + SSE stream endpoints."""

import json
import os
import re
import time
from typing import Any, Dict, Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend import schemas
from backend.chatflow import regenerate_chat, run_chat
from backend.deps import UserContext, bind_request_user, current_user

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/send", response_model=schemas.SendResponse)
def send(req: schemas.SendRequest, ctx: UserContext = Depends(current_user)):
    """Run one turn and return the full assistant message."""
    try:
        return run_chat(
            ctx,
            req.content,
            upload_ids=req.upload_ids,
            project_id=req.project_id,
            deep_mode=req.deep_mode,
            force_search=req.force_search,
            active_tier=req.active_tier,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/regenerate", response_model=schemas.SendResponse)
def regenerate(req: schemas.RegenerateRequest,
               ctx: UserContext = Depends(current_user)):
    """Append a fresh answer to an existing assistant message."""
    try:
        return regenerate_chat(
            ctx,
            int(req.index),
            project_id=req.project_id,
            deep_mode=req.deep_mode,
            force_search=req.force_search,
            active_tier=req.active_tier,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


def _word_chunks(text: str, max_chunks: int = 40):
    """Split text into ~max_chunks word-preserving pieces."""
    parts = re.split(r"(\s+)", text or "")
    words = [i for i, c in enumerate(parts) if c and not c.isspace()]
    if not words:
        return
    per = max(1, len(words) // max_chunks)
    for n in range(per, len(words) + per, per):
        end = words[min(n, len(words)) - 1] + 1
        yield "".join(parts[:end])


def _stream_delay() -> float:
    """Per-chunk pause so delivery reads as streaming, not a dump.

    Same knob as the old UI's typewriter (POKA_STREAM_DELAY, seconds;
    0 disables pacing). Short answers render instantly regardless.
    """
    try:
        return max(0.0, float(os.environ.get("POKA_STREAM_DELAY", "0.025")))
    except (TypeError, ValueError):
        return 0.025


@router.post("/stream")
def stream(req: schemas.SendRequest, ctx: UserContext = Depends(current_user)):
    """Run one turn, streaming the answer as SSE token deltas.

    Events (JSON per line): ``meta`` (tier/task), ``token`` (cumulative
    text so far), ``done`` (full SendResponse payload), ``error``.
    The answer still comes from the standard pipeline; streaming only
    affects delivery, never content.
    """
    user_id = ctx.user_id
    params: Dict[str, Any] = req.model_dump()

    def _events() -> Iterator[str]:
        # This generator runs on a different worker thread than the
        # endpoint: re-bind the user, then reuse the request's stores
        # (plain path holders, safe across threads).
        bind_request_user(user_id)
        thread_ctx = ctx
        try:
            payload = run_chat(
                thread_ctx,
                params["content"],
                upload_ids=params.get("upload_ids") or [],
                project_id=params.get("project_id"),
                deep_mode=bool(params.get("deep_mode", False)),
                force_search=bool(params.get("force_search", False)),
                active_tier=params.get("active_tier"),
            )
        except HTTPException as e:
            yield "data: " + json.dumps(
                {"type": "error", "detail": str(e.detail)}) + "\n\n"
            return
        except ValueError as e:
            yield "data: " + json.dumps(
                {"type": "error", "detail": str(e)}) + "\n\n"
            return
        except RuntimeError as e:
            yield "data: " + json.dumps(
                {"type": "error", "detail": str(e)}) + "\n\n"
            return
        message = payload["message"]
        yield "data: " + json.dumps({
            "type": "meta",
            "active_tier": payload.get("active_tier", ""),
            "task_type": payload.get("task_type", ""),
        }) + "\n\n"
        chunks = list(_word_chunks(str(message.get("content", ""))))
        delay = _stream_delay() if len(chunks) > 1 else 0.0
        for partial in chunks:
            yield "data: " + json.dumps(
                {"type": "token", "text": partial}) + "\n\n"
            if delay > 0:
                time.sleep(delay)
        yield "data: " + json.dumps({"type": "done", "result": payload}) + "\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")
