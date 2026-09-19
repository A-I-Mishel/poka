"""Chat send + SSE stream endpoints."""

import json
import logging
import queue
import threading
from typing import Any, AsyncIterator, Dict

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent.budget import TurnCancelled
from backend import schemas
from backend.chatflow import regenerate_chat, run_chat
from backend.deps import UserContext, bind_request_user, current_user
from services.obs import event as obs_event
from services.storage import StorageError

logger: logging.Logger = logging.getLogger(__name__)

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
    except TurnCancelled:
        raise HTTPException(status_code=503, detail="Request cancelled.")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=503, detail=f"Storage unavailable ({e})")


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
    except StorageError as e:
        raise HTTPException(status_code=503, detail=f"Storage unavailable ({e})")


_KEEPALIVE_SECONDS = 15.0


@router.post("/stream")
def stream(req: schemas.SendRequest, request: Request,
           ctx: UserContext = Depends(current_user)):
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
    disconnect can never leave partial messages behind. Disconnects
    are detected every second: the turn aborts between tool rounds
    (TurnCancelled, no synthesis, no persistence) instead of burning
    quota for a closed tab.
    """
    user_id = ctx.user_id
    limit_key = ctx.limit_key or ctx.user_id
    source = ctx.source or ""
    params: Dict[str, Any] = req.model_dump()

    async def _events() -> AsyncIterator[str]:
        events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        outcome: Dict[str, Any] = {}
        cancelled = threading.Event()

        def _run() -> None:
            # Separate worker: the generator must stay free to yield
            # tokens while the pipeline runs. Re-bind the user
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
                    cancel=cancelled.is_set,
                )
            except TurnCancelled:
                outcome["cancelled"] = True
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
        idle_ticks = 0
        try:
            while True:
                try:
                    evt = await anyio.to_thread.run_sync(
                        lambda: events.get(timeout=1.0))
                except queue.Empty:
                    idle_ticks += 1
                    try:
                        gone = await request.is_disconnected()
                    except Exception:
                        gone = False
                    if gone:
                        cancelled.set()
                        break
                    if idle_ticks >= int(_KEEPALIVE_SECONDS):
                        idle_ticks = 0
                        yield ": ping\n\n"
                    continue
                idle_ticks = 0
                kind = evt.get("type")
                if kind == "end":
                    break
                if kind == "reset":
                    yield "data: " + json.dumps({"type": "reset"}) + "\n\n"
                elif kind == "token":
                    yield "data: " + json.dumps(
                        {"type": "token", "text": evt.get("text", "")}) + "\n\n"
                elif kind == "status":
                    yield "data: " + json.dumps(
                        {"type": "status", "text": evt.get("text", "")}) + "\n\n"
        finally:
            # Never block the response on a worker finishing a bounded
            # provider call after a disconnect; daemon threads die alone.
            await anyio.to_thread.run_sync(lambda: worker.join(timeout=10.0))
        if outcome.get("cancelled"):
            try:
                obs_event("request.cancelled", user=user_id)
            except Exception:
                logger.debug("obs_event cancelled failed", exc_info=True)
            return
        if "error" in outcome:
            yield "data: " + json.dumps(
                {"type": "error", "detail": outcome["error"]}) + "\n\n"
            return
        payload = outcome["payload"]
        yield "data: " + json.dumps({
            "type": "meta",
            "active_tier": payload.get("active_tier", ""),
            "task_type": payload.get("task_type", ""),
            "fallback": payload.get("fallback"),
            "corrections": payload.get("corrections", []),
        }) + "\n\n"
        yield "data: " + json.dumps({"type": "done", "result": payload}) + "\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")
