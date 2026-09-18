"""Human approval endpoints for irreversible tool actions.

The model can only stage an approval (via a tool call without a token);
execution happens here, server-side, with a single-use token the model
never sees. Approving consumes the token first (no double-spend on
double-click), then runs the stored action and returns its result.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from backend import schemas
from backend.deps import UserContext, current_user
from services import approvals as approvals_svc

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

_APPROVAL_EXECUTORS = ("send_gmail", "delete_calendar_event",
                       "import_csv_table", "execute_sql")


def _execute_stored(user_id: Any, tool: str, args: Dict[str, Any]) -> str:
    """Run a consumed approval's stored action (server-side only)."""
    if tool == "send_gmail":
        from tools.gmail_tool import _execute_send_gmail

        return _execute_send_gmail(str(args.get("to", "")),
                                   str(args.get("subject", "")),
                                   str(args.get("body", "")))
    if tool == "delete_calendar_event":
        from tools.calendar_tool import _execute_delete_calendar_event

        return _execute_delete_calendar_event(str(args.get("event_id", "")))
    if tool == "import_csv_table":
        from tools.database_tool import _execute_import_csv_table

        return _execute_import_csv_table(str(args.get("upload_id", "")),
                                         str(args.get("table", "")))
    if tool == "execute_sql":
        from tools.database_tool import _execute_write_sql

        return _execute_write_sql(str(args.get("sql", "")))
    return f"STATUS=INVALID approval: unknown tool '{tool}'."


@router.get("")
def list_approvals(ctx: UserContext = Depends(current_user)):
    """List pending approvals (fresh single-use tokens included)."""
    try:
        items = approvals_svc.list_pending(ctx.user_id, rotate_tokens=True)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load approvals.")
    return {"approvals": items}


@router.post("/{approval_id}/approve")
def approve_action(approval_id: str, body: schemas.ApprovalDecision,
                   ctx: UserContext = Depends(current_user)):
    """Consume the token and execute the stored action exactly once."""
    pending = approvals_svc.get_pending(ctx.user_id, str(approval_id or ""))
    if pending is None:
        raise HTTPException(status_code=410, detail="Approval not found or expired.")
    if pending.get("tool") not in _APPROVAL_EXECUTORS:
        raise HTTPException(status_code=400, detail="Tool cannot be approved.")
    # Consume compares tool+stored-args+token atomically under lock, so
    # execution below can only ever run the exact staged action.
    stored_args = approvals_svc.peek_args(ctx.user_id, str(pending["id"]))
    ok, result = approvals_svc.consume_approval(
        ctx.user_id, str(pending.get("tool", "")), stored_args,
        str(body.token or ""))
    if not ok:
        raise HTTPException(
            status_code=410,
            detail=f"Approval invalid, expired, or already used ({result}).")
    try:
        output = _execute_stored(ctx.user_id, str(pending.get("tool", "")), result)
    except Exception as e:
        output = f"STATUS=FAILED approval: execution failed ({e})."
    return {"ok": True, "tool": pending.get("tool", ""), "result": output}


@router.post("/{approval_id}/reject")
def reject_action(approval_id: str, ctx: UserContext = Depends(current_user)):
    """Discard a pending approval without executing it."""
    if not approvals_svc.reject_approval(ctx.user_id, str(approval_id or "")):
        raise HTTPException(status_code=404, detail="Approval not found.")
    return {"ok": True}
