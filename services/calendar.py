"""Google Calendar integration: list, create, and delete events.

Desktop-app OAuth client (GOOGLE_CLIENT_ID / SECRET /
REFRESH_TOKEN); the refresh token must carry the calendar scope
(re-consent after adding it). Unconfigured -> degraded markers, never
raises into the agent. Deletion is gated at the tool layer.

Test seam: configure_service() installs a fake service (google client
libraries are imported lazily so the module loads without them).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.google import CALENDAR_SCOPES
from services.google import build_google_service
from services.obs import event as obs_event

MAX_LIST_RESULTS: int = 25

_service_override: Any = None


def configure_service(service: Any) -> None:
    """Install a fake Calendar service (tests), or None to restore default."""
    global _service_override
    _service_override = service


def get_service() -> Optional[Any]:
    """Build the Calendar client, or None when unconfigured (never raises)."""
    if _service_override is not None:
        return _service_override
    return build_google_service("calendar", "v3", list(CALENDAR_SCOPES))


def _fmt_when(ev: Dict[str, Any]) -> str:
    start = (ev.get("start") or {}) if isinstance(ev.get("start"), dict) else {}
    end = (ev.get("end") or {}) if isinstance(ev.get("end"), dict) else {}
    s = str(start.get("dateTime") or start.get("date") or "?")
    e = str(end.get("dateTime") or end.get("date") or "")
    return s if not e or e == s else s + " -> " + e


def summarize_event(ev: Dict[str, Any]) -> Dict[str, str]:
    """Stable subset of an event record (never raises)."""
    try:
        return {
            "id": str(ev.get("id", "")),
            "summary": str(ev.get("summary") or "(no title)"),
            "when": _fmt_when(ev),
            "location": str(ev.get("location") or ""),
            "link": str(ev.get("htmlLink") or ""),
        }
    except Exception:
        return {"id": "", "summary": "(unreadable)", "when": "", "location": "", "link": ""}


def list_events(service: Any, time_min: str = "", time_max: str = "",
                query: str = "", max_results: int = MAX_LIST_RESULTS) -> List[Dict[str, str]]:
    """Upcoming events (defaults: from now), optionally filtered by text."""
    if not time_min:
        time_min = datetime.now(timezone.utc).isoformat()
    try:
        resp = (
            service.events()
            .list(calendarId="primary", timeMin=time_min,
                  **({"timeMax": time_max} if time_max else {}),
                  **({"q": query} if query else {}),
                  maxResults=max(1, min(int(max_results), 50)),
                  singleEvents=True, orderBy="startTime")
            .execute()
        )
    except Exception as e:
        obs_event("calendar.error", action="list")
        raise RuntimeError(f"Calendar list failed: {e}")
    return [summarize_event(e) for e in ((resp or {}).get("items", []) or []) if isinstance(e, dict)]


def _parse_time(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty datetime")
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def create_event(service: Any, summary: str, start: str, end: str = "",
                 timezone_name: str = "UTC", description: str = "",
                 location: str = "") -> Dict[str, str]:
    """Create an event (default duration 1h). Returns {id, link}."""
    try:
        start_dt = _parse_time(start)
        end_dt = _parse_time(end) if end else start_dt + timedelta(hours=1)
    except ValueError:
        raise ValueError("Use ISO datetimes, e.g. 2026-09-13T10:00:00+06:00.")
    if end_dt <= start_dt:
        raise ValueError("Event end must be after start.")
    body = {
        "summary": summary or "(no title)",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone_name or "UTC"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone_name or "UTC"},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    try:
        created = (
            service.events()
            .insert(calendarId="primary", body=body)
            .execute()
        )
    except Exception as e:
        obs_event("calendar.error", action="create")
        raise RuntimeError(f"Calendar create failed: {e}")
    return {"id": str((created or {}).get("id", "")),
            "link": str((created or {}).get("htmlLink", ""))}


def delete_event(service: Any, event_id: str) -> Dict[str, str]:
    """Delete an event. Gated on confirmation at the tool layer."""
    if not str(event_id or "").strip():
        raise ValueError("Empty event id.")
    try:
        service.events().delete(calendarId="primary", eventId=str(event_id).strip()).execute()
    except Exception as e:
        obs_event("calendar.error", action="delete")
        raise RuntimeError(f"Calendar delete failed: {e}")
    return {"deleted": str(event_id).strip()}
