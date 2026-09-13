"""Workflow endpoints: CRUD for saved pipelines + deterministic runs."""

from fastapi import APIRouter, Depends, HTTPException

from backend import schemas
from backend.deps import UserContext, current_user
from services.storage import StorageError

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _known_tools():
    """Live tool names for save-time validation (lazy: avoids import weight)."""
    from agent.toolrun import TOOL_MAP

    return set(TOOL_MAP)


@router.get("")
def list_workflows(ctx: UserContext = Depends(current_user)):
    """List saved pipelines (newest first)."""
    try:
        return {"workflows": ctx.user_store.list_workflows()}
    except StorageError as e:
        raise HTTPException(status_code=500, detail=f"Could not load workflows: {e}")
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load workflows.")


@router.post("", status_code=201)
def create_workflow(body: schemas.WorkflowCreate,
                    ctx: UserContext = Depends(current_user)):
    """Save a fixed tool pipeline (validated: templates, sinks, caps)."""
    try:
        return ctx.user_store.create_workflow(
            body.name,
            [step.model_dump() for step in body.steps],
            body.description,
            _known_tools(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not save workflow.")


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, ctx: UserContext = Depends(current_user)):
    """Fetch one pipeline."""
    try:
        record = ctx.user_store.get_workflow(workflow_id)
    except StorageError:
        raise HTTPException(status_code=500, detail="Could not load workflow.")
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load workflow.")
    if record is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return record


@router.put("/{workflow_id}")
def update_workflow(workflow_id: str, body: schemas.WorkflowUpdate,
                    ctx: UserContext = Depends(current_user)):
    """Full-replace a pipeline (re-validated; id/created survive)."""
    try:
        return ctx.user_store.update_workflow(
            workflow_id,
            body.name,
            [step.model_dump() for step in body.steps],
            body.description,
            _known_tools(),
        )
    except ValueError as e:
        msg = str(e)
        raise HTTPException(
            status_code=404 if msg == "Workflow not found." else 400, detail=msg)
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Could not update workflow.")


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: str, ctx: UserContext = Depends(current_user)):
    """Delete a pipeline."""
    try:
        removed = ctx.user_store.delete_workflow(workflow_id)
    except StorageError:
        removed = False
    except Exception:
        removed = False
    if not removed:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return {"ok": True}


@router.post("/{workflow_id}/run")
def run_workflow(workflow_id: str, body: schemas.WorkflowRunRequest,
                 ctx: UserContext = Depends(current_user)):
    """Run a pipeline deterministically (no LLM planning).

    Always 200 with a structured result (status ok/failed/partial):
    a failed run is data, not an HTTP error. Unknown IDs are 404.
    """
    try:
        record = ctx.user_store.get_workflow(workflow_id)
    except StorageError:
        raise HTTPException(status_code=500, detail="Could not load workflow.")
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load workflow.")
    if record is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    try:
        from agent.workflows import run_workflow as _run
    except Exception:
        raise HTTPException(status_code=500, detail="Workflow runner unavailable.")
    try:
        return _run(record, body.input, ctx.user_id, ctx.limit_key)
    except Exception:
        raise HTTPException(status_code=500, detail="Workflow run failed.")
