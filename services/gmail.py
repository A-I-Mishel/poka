"""Gmail integration: search, read, draft, and send via the Gmail API.

Single configured account (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET /
GOOGLE_REFRESH_TOKEN in env). Everything degrades gracefully: without
credentials every operation reports unconfigured instead of raising
into the agent. Raw tokens are never logged.

Mail content is untrusted DATA (prompt-injection boundary holds);
sending is gated at the tool layer (explicit user confirmation).

Test seam: configure_service() installs a fake service (the real
googleapiclient chain is only imported lazily so the module loads
without credentials or network).
"""

import base64
import logging
from typing import Any, Dict, List, Optional

from services.google import GMAIL_SCOPES as SCOPES
from services.google import build_google_service
from services.obs import event as obs_event

logger = logging.getLogger(__name__)

MAX_BODY_CHARS: int = 20000
MAX_SEARCH_RESULTS: int = 10

_service_override: Any = None


def configure_service(service: Any) -> None:
    """Install a fake Gmail service (tests), or None to restore default."""
    global _service_override
    _service_override = service


def _credentials() -> Optional[Any]:
    """OAuth credentials from env refresh token, or None when unconfigured."""
    from services.google import google_credentials

    return google_credentials(list(SCOPES))


def get_service() -> Optional[Any]:
    """Build the Gmail client, or None when unconfigured (never raises)."""
    if _service_override is not None:
        return _service_override
    return build_google_service("gmail", "v1", list(SCOPES))


def _headers(payload: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        for h in payload.get("headers", []) or []:
            if isinstance(h, dict) and h.get("name"):
                out[str(h["name"]).lower()] = str(h.get("value", ""))
    except Exception:
        logger.debug("gmail header parse failed", exc_info=True)
    return out


def extract_plain_text(payload: Dict[str, Any]) -> str:
    """Best-effort plain-text body from a Gmail payload (never raises).

    Prefers text/plain parts (joined); falls back to text/html only
    when no plain part exists.
    """
    try:
        plains: List[str] = []
        htmls: List[str] = []
        _collect_text(payload or {}, plains, htmls)
        texts = plains or htmls
        return "\n".join(texts)[:MAX_BODY_CHARS]
    except Exception:
        return ""


def _decode_body(data: Any) -> str:
    try:
        s = str(data or "").strip().replace("-", "+").replace("_", "/")
        # Gmail omits padding; restore it.
        pad = (-len(s)) % 4
        if pad:
            s += "=" * pad
        return base64.b64decode(s).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _collect_text(part: Dict[str, Any], plains: List[str], htmls: List[str]) -> None:
    mime = str(part.get("mimeType", "") or "")
    body = part.get("body", {}) if isinstance(part.get("body"), dict) else {}
    data = body.get("data", "")
    if mime.startswith("text/plain") and data:
        text = _decode_body(data)
        if text:
            plains.append(text)
        return
    if mime.startswith("text/html") and data:
        text = _decode_body(data)
        if text:
            htmls.append(text)
        return
    for sub in part.get("parts", []) or []:
        if isinstance(sub, dict):
            _collect_text(sub, plains, htmls)


def search_messages(service: Any, query: str, max_results: int = MAX_SEARCH_RESULTS) -> List[Dict[str, str]]:
    """Search mail; returns [{id, subject, sender, date, snippet}]."""
    try:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=query or "", maxResults=max(1, min(int(max_results), 25)))
            .execute()
        )
    except Exception as e:
        obs_event("gmail.error", action="search")
        raise RuntimeError(f"Gmail search failed: {e}")
    out: List[Dict[str, str]] = []
    for m in (resp or {}).get("messages", []) or []:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        try:
            full = (
                service.users()
                .messages()
                .get(userId="me", id=m["id"], format="metadata",
                     metadataHeaders=["Subject", "From", "Date"])
                .execute()
            )
        except Exception:
            logger.debug("gmail message fetch failed; skipping message", exc_info=True)
            continue
        headers = _headers((full or {}).get("payload", {}))
        out.append({
            "id": str(m["id"]),
            "subject": headers.get("subject", "(no subject)"),
            "sender": headers.get("from", "unknown"),
            "date": headers.get("date", ""),
            "snippet": str((full or {}).get("snippet", ""))[:300],
        })
    return out


def read_message(service: Any, message_id: str) -> Dict[str, str]:
    """Read one message: {subject, sender, date, body} (body capped)."""
    try:
        full = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
    except Exception as e:
        obs_event("gmail.error", action="read")
        raise RuntimeError(f"Gmail read failed: {e}")
    headers = _headers((full or {}).get("payload", {}))
    return {
        "subject": headers.get("subject", "(no subject)"),
        "sender": headers.get("from", "unknown"),
        "date": headers.get("date", ""),
        "body": extract_plain_text((full or {}).get("payload", {})),
    }


def _raw_message(to: str, subject: str, body: str) -> Dict[str, str]:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body or "")
    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}


def create_draft(service: Any, to: str, subject: str, body: str) -> Dict[str, str]:
    """Save a draft (safe default: nothing is sent). Returns {id}."""
    try:
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": _raw_message(to, subject, body)})
            .execute()
        )
    except Exception as e:
        obs_event("gmail.error", action="draft")
        raise RuntimeError(f"Gmail draft failed: {e}")
    return {"id": str((draft or {}).get("id", ""))}


def send_message(service: Any, to: str, subject: str, body: str) -> Dict[str, str]:
    """Send an email. Irreversible: the tool layer gates on confirmation."""
    try:
        sent = (
            service.users()
            .messages()
            .send(userId="me", body=_raw_message(to, subject, body))
            .execute()
        )
    except Exception as e:
        obs_event("gmail.error", action="send")
        raise RuntimeError(f"Gmail send failed: {e}")
    return {"id": str((sent or {}).get("id", ""))}
