"""Calendar tools: list upcoming events, create events, delete (gated).

Creating is low-risk (visible on the user's own calendar, trivially
undoable). Deleting runs only with a server-minted single-use approval
token from the authenticated UI — never a model-supplied flag.

Single-account note: the host configures ONE Google calendar via
GOOGLE_* env vars. Every app user would share it, so these tools are
private-mode only (PLUTO_AUTH_MODE=private), like Gmail — open mode
is denied outright.
"""

import logging

from langchain_core.tools import tool

from services import calendar as calendar_svc
from services.identity import auth_mode
from services.obs import event as obs_event
from tools.gating import claim_tool_slot

logger: logging.Logger = logging.getLogger(__name__)


def _gate(tool_name: str):
    """Private-mode + user context + rate check + service, or (None, error)."""
    if auth_mode() != "private":
        obs_event("ratelimit.deny", action="calendar", tool=tool_name, reason="open_mode")
        return None, (
            f"STATUS=DENIED tool={tool_name}: Calendar is disabled "
            "in open mode (single shared calendar would leak to visitors). "
            "Set PLUTO_AUTH_MODE=private (trusted/owner use only)."
        )
    user_id, err = claim_tool_slot(tool_name, "calendar", "Calendar")
    if user_id is None:
        return None, err
    service = calendar_svc.get_service()
    if service is None:
        return None, (
            f"STATUS=DEGRADED tool={tool_name}: Calendar is not connected. "
            "Set GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REFRESH_TOKEN "
            "(refresh token must carry the calendar scope)."
        )
    return service, ""


@tool
def list_calendar_events(query: str = "", max_results: int = 10) -> str:
    """List upcoming calendar events, optionally filtered by text.

    Use when the user asks what's on their schedule ("what's next?",
    "any meetings Friday?", ...).

    Args:
        query: Free-text filter (optional).
        max_results: Max events (1-25).

    Returns:
        Numbered events (id, title, when, location), or a structured
        failure marker (never silent).
    """
    service, err = _gate("list_calendar_events")
    if service is None:
        return err
    try:
        max_n = max(1, min(int(max_results or 10), 25))
    except (TypeError, ValueError):
        max_n = 10
    try:
        events = calendar_svc.list_events(service, query=str(query or ""), max_results=max_n)
    except Exception as e:
        logger.warning("Calendar list failed: %s", e)
        return f"STATUS=FAILED tool=list_calendar_events: {e}"
    if not events:
        return "STATUS=EMPTY tool=list_calendar_events: no upcoming events."
    lines = []
    for i, e in enumerate(events, 1):
        line = f"[{i}] id={e['id']} | {e['summary']} | {e['when']}"
        if e["location"]:
            line += f" | {e['location']}"
        lines.append(line)
    return "\n".join(lines)


@tool
def create_calendar_event(summary: str, start: str, end: str = "",
                          timezone_name: str = "UTC", description: str = "",
                          location: str = "") -> str:
    """Create a calendar event.

    Use when the user asks to schedule something. Times are ISO
    datetimes with offset, e.g. 2026-09-13T10:00:00+06:00; end
    defaults to start + 1 hour.

    Args:
        summary: Event title.
        start: Start ISO datetime (required).
        end: End ISO datetime (optional).
        timezone_name: IANA zone for display (optional).
        description: Details (optional).
        location: Place (optional).

    Returns:
        The event id + link, or a structured failure marker.
    """
    service, err = _gate("create_calendar_event")
    if service is None:
        return err
    if not str(summary or "").strip() or not str(start or "").strip():
        return "STATUS=INVALID tool=create_calendar_event: summary and start are required."
    try:
        created = calendar_svc.create_event(
            service, str(summary).strip(), str(start).strip(),
            str(end or "").strip(), str(timezone_name or "UTC"),
            str(description or ""), str(location or ""))
    except ValueError as e:
        return f"STATUS=INVALID tool=create_calendar_event: {e}"
    except Exception as e:
        logger.warning("Calendar create failed: %s", e)
        return f"STATUS=FAILED tool=create_calendar_event: {e}"
    suffix = f" link={created['link']}" if created.get("link") else ""
    return f"STATUS=OK tool=create_calendar_event event_id={created['id']}{suffix}"


def _execute_delete_calendar_event(event_id: str) -> str:
    """Delete after authorization (gate + approval already checked)."""
    service, err = _gate("delete_calendar_event")
    if service is None:
        return err
    try:
        deleted = calendar_svc.delete_event(service, event_id)
    except ValueError as e:
        return f"STATUS=INVALID tool=delete_calendar_event: {e}"
    except Exception as e:
        logger.warning("Calendar delete failed: %s", e)
        return f"STATUS=FAILED tool=delete_calendar_event: {e}"
    return f"STATUS=OK tool=delete_calendar_event deleted_id={deleted['deleted']}"


@tool
def delete_calendar_event(event_id: str, approval_token: str = "") -> str:
    """Delete a calendar event. UI approval required.

    Call WITHOUT approval_token first (use an id from
    list_calendar_events). If the result is DENIED with an approval_id,
    describe the deletion and ask the user to approve it in the UI.
    Never invent an approval token.

    Args:
        event_id: The event id.
        approval_token: Server-minted single-use token (UI only).

    Returns:
        Confirmation, or a structured failure marker.
    """
    from services import approvals as approvals_svc
    from services.context import get_current_user_id

    if auth_mode() != "private":
        return (
            "STATUS=DENIED tool=delete_calendar_event: Calendar is disabled "
            "in open mode (single shared calendar would leak to visitors). "
            "Set PLUTO_AUTH_MODE=private (trusted/owner use only)."
        )
    user_id = get_current_user_id()
    if not user_id:
        return "STATUS=DENIED tool=delete_calendar_event: no user context."
    event_id = str(event_id or "").strip()
    if not event_id:
        return "STATUS=INVALID tool=delete_calendar_event: empty event id."
    action = {"event_id": event_id}
    if approval_token:
        ok, stored = approvals_svc.consume_approval(
            user_id, "delete_calendar_event", action, str(approval_token))
        if not ok:
            return (
                "STATUS=DENIED tool=delete_calendar_event: approval token "
                f"invalid, expired, or already used ({stored}). Deleted nothing."
            )
        action = stored
    else:
        summary = f"Delete calendar event {event_id}"
        approval_id, _token, _created = approvals_svc.request_approval(
            user_id, "delete_calendar_event", action, summary)
        if not approval_id:
            return "STATUS=FAILED tool=delete_calendar_event: could not stage approval."
        return (
            "STATUS=DENIED tool=delete_calendar_event: approval required "
            f"(approval_id={approval_id}). {summary}. Deleted nothing; ask "
            "the user to approve it in the UI."
        )
    return _execute_delete_calendar_event(action["event_id"])
