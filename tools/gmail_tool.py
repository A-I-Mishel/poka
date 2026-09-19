"""Gmail tools: search inbox, read mail, draft, and send (gated).

Mail content is untrusted DATA. Sending is irreversible, so
send_gmail runs only with a server-minted single-use approval token
from the authenticated UI — never a model-supplied flag. Drafts are
the safe default and need no confirmation.

Single-account note: the host configures ONE Google account via
GOOGLE_* env vars. Every app user would share that mailbox, so these
tools are private-mode only (PLUTO_AUTH_MODE=private, trusted owner),
like code execution — open mode is denied outright.
"""

import logging
import re

from langchain_core.tools import tool

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(addr: str) -> bool:
    text = str(addr or "").strip()
    if not _EMAIL_RE.match(text):
        return False
    # no consecutive dots, no leading/trailing dot in local/domain
    if ".." in text:
        return False
    local, domain = text.rsplit("@", 1)
    if local.startswith(".") or local.endswith(".") or domain.startswith(".") or domain.endswith("."):
        return False
    return True

from services import gmail as gmail_svc
from services.identity import auth_mode
from services.obs import event as obs_event
from tools.gating import claim_tool_slot

logger: logging.Logger = logging.getLogger(__name__)


def _gate(tool_name: str):
    """Private-mode + user context + rate check + service, or (None, error)."""
    if auth_mode() != "private":
        obs_event("ratelimit.deny", action="gmail", tool=tool_name, reason="open_mode")
        return None, (
            f"STATUS=DENIED tool={tool_name}: Gmail is disabled "
            "in open mode (single shared mailbox would leak to visitors). "
            "Set PLUTO_AUTH_MODE=private (trusted/owner use only)."
        )
    user_id, err = claim_tool_slot(tool_name, "gmail", "Gmail")
    if user_id is None:
        return None, err
    service = gmail_svc.get_service()
    if service is None:
        return None, (
            f"STATUS=DEGRADED tool={tool_name}: Gmail is not connected. "
            "Set GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REFRESH_TOKEN."
        )
    return service, ""


@tool
def search_gmail(query: str) -> str:
    """Search the user's Gmail inbox.

    Use when the user asks about their emails ("did X reply?", "find
    the invoice", ...). Gmail search syntax works (from:, subject:,
    newer_than:, ...).

    Args:
        query: Gmail search query. Empty lists recent mail.

    Returns:
        Numbered messages (id, subject, sender, date, snippet), or a
        structured failure marker (never silent).
    """
    service, err = _gate("search_gmail")
    if service is None:
        return err
    try:
        hits = gmail_svc.search_messages(service, str(query or ""))
    except Exception as e:
        logger.warning("Gmail search failed: %s", e)
        return f"STATUS=FAILED tool=search_gmail: {str(e)[:200]}"
    if not hits:
        return "STATUS=EMPTY tool=search_gmail: no matching emails."
    lines = []
    for i, h in enumerate(hits, 1):
        if not isinstance(h, dict):
            continue
        lines.append(
            f"[{i}] id={h.get('id','?')} | {str(h.get('subject',''))[:200]} | {str(h.get('sender',''))[:120]} | {h.get('date','')}\n"
            f"    {str(h.get('snippet',''))[:500]}"
        )
    return "\n".join(lines)


@tool
def read_gmail(message_id: str) -> str:
    """Read one Gmail message in full (use an id from search_gmail).

    Args:
        message_id: The Gmail message id.

    Returns:
        Subject/sender/date plus the plain-text body (capped), or a
        structured failure marker (never silent).
    """
    service, err = _gate("read_gmail")
    if service is None:
        return err
    if not str(message_id or "").strip():
        return "STATUS=INVALID tool=read_gmail: empty message id."
    try:
        msg = gmail_svc.read_message(service, str(message_id).strip())
    except Exception as e:
        logger.warning("Gmail read failed: %s", e)
        return f"STATUS=FAILED tool=read_gmail: {str(e)[:200]}"
    if not isinstance(msg, dict):
        return "STATUS=FAILED tool=read_gmail: bad service response."
    return (
        f"Subject: {str(msg.get('subject',''))[:300]}\nFrom: {str(msg.get('sender',''))[:200]}\n"
        f"Date: {msg.get('date','')}\n\n{str(msg.get('body',''))[:4000]}"
    )


@tool
def create_gmail_draft(to: str, subject: str, body: str) -> str:
    """Save a Gmail draft (nothing is sent; the safe default).

    Use when the user wants an email prepared for review, or when they
    have not explicitly asked you to send it.

    Args:
        to: Recipient email address.
        subject: Email subject.
        body: Plain-text body.

    Returns:
        The draft id, or a structured failure marker (never silent).
    """
    service, err = _gate("create_gmail_draft")
    if service is None:
        return err
    to = str(to or "").strip()
    if not _valid_email(to):
        return "STATUS=INVALID tool=create_gmail_draft: bad recipient address."
    try:
        draft = gmail_svc.create_draft(service, to, str(subject or ""), str(body or ""))
    except Exception as e:
        logger.warning("Gmail draft failed: %s", e)
        return f"STATUS=FAILED tool=create_gmail_draft: {str(e)[:200]}"
    did = draft.get('id','?') if isinstance(draft, dict) else '?'
    return f"STATUS=OK tool=create_gmail_draft draft_id={did}"


def _execute_send_gmail(to: str, subject: str, body: str) -> str:
    """Send after authorization (gate + approval already checked)."""
    service, err = _gate("send_gmail")
    if service is None:
        return err
    try:
        sent = gmail_svc.send_message(service, to, subject, body)
    except Exception as e:
        logger.warning("Gmail send failed: %s", e)
        return f"STATUS=FAILED tool=send_gmail: {str(e)[:200]}"
    sid = sent.get('id','?') if isinstance(sent, dict) else '?'
    return f"STATUS=OK tool=send_gmail sent_id={sid}"


@tool
def send_gmail(to: str, subject: str, body: str, approval_token: str = "") -> str:
    """Send a Gmail email. IRREVERSIBLE — UI approval required.

    Call WITHOUT approval_token first. If the result is DENIED with an
    approval_id, describe the email and ask the user to approve it in
    the UI; otherwise save a draft with create_gmail_draft instead.
    Never invent an approval token.

    Args:
        to: Recipient email address.
        subject: Email subject.
        body: Plain-text body.
        approval_token: Server-minted single-use token (UI only).

    Returns:
        The sent message id, or a structured failure marker.
    """
    from services import approvals as approvals_svc
    from services.context import get_current_user_id
    from services.context import get_limit_key as _glk
    from services.ratelimit import get_rate_limiter as _grl

    if auth_mode() != "private":
        return (
            "STATUS=DENIED tool=send_gmail: Gmail is disabled "
            "in open mode (single shared mailbox would leak to visitors). "
            "Set PLUTO_AUTH_MODE=private (trusted/owner use only)."
        )
    user_id = get_current_user_id()
    if not user_id:
        return "STATUS=DENIED tool=send_gmail: no user context."
    to = str(to or "").strip()
    if not _valid_email(to):
        return "STATUS=INVALID tool=send_gmail: bad recipient address."
    action = {"to": to, "subject": str(subject or ""), "body": str(body or "")}
    if approval_token:
        ok, stored = approvals_svc.consume_approval(
            user_id, "send_gmail", action, str(approval_token))
        if not ok:
            return (
                "STATUS=DENIED tool=send_gmail: approval token invalid, "
                f"expired, or already used ({stored}). Saved nothing."
            )
        action = stored
        # Re-validate server-stored values (never trust caller alongside token).
        if not _valid_email(str(action.get("to", "") or "")):
            return "STATUS=INVALID tool=send_gmail: bad recipient address."
    else:
        # Rate-limit approval staging (otherwise spam mints unbounded pendings).
        try:
            _v = _grl().check(_glk() or user_id, "gmail")
            if not _v.allowed:
                return (
                    "STATUS=DENIED tool=send_gmail: Gmail rate limit "
                    f"exceeded, retry in {_v.retry_after:.0f}s."
                )
        except Exception:
            logger.debug("send_gmail staging rate-check failed", exc_info=True)
        summary = f"Send email to {to} — {str(subject or '')[:80]}".strip()
        approval_id, _token, _created = approvals_svc.request_approval(
            user_id, "send_gmail", action, summary)
        if not approval_id:
            return "STATUS=FAILED tool=send_gmail: could not stage approval."
        return (
            "STATUS=DENIED tool=send_gmail: approval required "
            f"(approval_id={approval_id}). {summary}. Saved nothing; ask the "
            "user to approve it in the UI, or use create_gmail_draft to "
            "prepare it instead."
        )
    return _execute_send_gmail(action["to"], action["subject"], action["body"])
