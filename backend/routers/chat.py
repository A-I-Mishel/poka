"""Chat send + SSE stream endpoints."""

import json
import queue
import threading
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


_KEEPALIVE_SECONDS = 15.0


@router.post("/stream")
def stream(req: schemas.SendRequest, ctx: UserContext = Depends(current_user)):
    """Run one turn, streaming the answer's real tokens as SSE.

    Events (JSON per line): ``token`` (cumulative answer text — genuine
    provider tokens forwarded live, never replayed), ``reset`` (a new
    model call supersedes earlier text: discard it and keep waiting),
    ``status`` (per-tool-round activity, tool names only — shown while
    no answer tokens flow yet), ``meta`` (tier/task, once the turn
    completes), ``done`` (full send-response payload, same shape as
    /send), ``error``. ``: ping`` comments keep idle connections alive
    during long generations.
    History is persisted exactly once, when the turn completes — a
    disconnect can never leave partial messages behind.
    """
    user_id = ctx.user_id
    limit_key = ctx.limit_key or ctx.user_id
    source = ctx.source or ""
    params: Dict[str, Any] = req.model_dump()

    def _events() -> Iterator[str]:
        events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        outcome: Dict[str, Any] = {}

        def _run() -> None:
            # Separate worker: the generator thread must stay free to
            # yield tokens while the pipeline runs. Re-bind the user
            # (contextvars do not cross threads), then reuse the
            # request's stores (plain path holders, safe across threads).
            bind_request_user(user_id, limit_key, source)
            try:
                outcome["payload"] = run_chat(
                    ctx,
                    params["content"],
                    upload_ids=params.get("upload_ids") or [],
                    project_id=params.get("project_id"),
                    deep_mode=bool(params.get("deep_mode", False)),
                    force_search=bool(params.get("force_search", False)),
                    active_tier=params.get("active_tier"),
                    on_token=lambda text: events.put({"type": "token", "text": text}),
                    on_reset=lambda: events.put({"type": "reset"}),
                    on_progress=lambda text: events.put({"type": "status", "text": text}),
                )
            except HTTPException as e:
                outcome["error"] = str(e.detail)
            except (ValueError, RuntimeError) as e:
                outcome["error"] = str(e)
            except Exception:
                outcome["error"] = "Internal error."
            finally:
                events.put({"type": "end"})

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        while True:
            try:
                evt = events.get(timeout=_KEEPALIVE_SECONDS)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            kind = evt.get("type")
            if kind == "end":
                break
            if kind == "reset":
                yield "data: " + json.dumps({"type": "reset"}) + "\n\n"
            elif kind == "status":
                yield "data: " + json.dumps(
                    {"type": "status", "text": evt.get("text", "")}) + "\n\n"
            elif kind == "token":
                yield "data: " + json.dumps(
                    {"type": "token", "text": evt.get("text", "")}) + "\n\n"
        worker.join()
        if "error" in outcome:
            yield "data: " + json.dumps(
                {"type": "error", "detail": outcome["error"]}) + "\n\n"
            return
        payload = outcome["payload"]
        yield "data: " + json.dumps({
            "type": "meta",
            "active_tier": payload.get("active_tier", ""),
            "task_type": payload.get("task_type", ""),
        }) + "\n\n"
        yield "data: " + json.dumps({"type": "done", "result": payload}) + "\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")
