"""Framework-free chat pipeline backing send + stream endpoints.

Mirrors ui/chat.render_assistant_response without any Streamlit
dependency: attachment hints, history building, agent invocation,
provenance capture, artifact linkage, and persistence. The React
frontend owns transient UI state; this module owns everything the
old page flow did with st.session_state.
"""

from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

import agent
from services.files import FileValidationError
from services.limits import (
    MAX_ATTACHMENTS_PER_MESSAGE,
    MAX_CHAT_TITLE_CHARS,
    MAX_DISPLAY_NAME_CHARS,
    MAX_IMAGE_ATTACHMENTS,
)
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter
from services.storage import (
    StorageError,
    clean_source_record,
    is_valid_id,
    new_conversation_id,
)
from services.timeutil import utcnow_iso

from backend.deps import UserContext


# --- attachment hints (same contract as the Streamlit composer) ---

def attachment_hint(kind: str, upload_id: str, name: str, index: int, total: int) -> str:
    """Tool hint for one staged attachment (ID-only, never paths)."""
    tag: str = "" if total <= 1 else f" {index}/{total}"
    if kind == "pdf":
        return (
            f"\n\n[Attached PDF{tag} '{name}' with upload ID: {upload_id}. "
            "To read it, call read_pdf(upload_id=\""
            f"{upload_id}"
            "\"). Never use any other path or ID.]"
        )
    if kind == "csv":
        return (
            f"\n\n[Attached CSV{tag} '{name}' with upload ID: {upload_id}. "
            "To analyze it, call analyze_csv(upload_id=\""
            f"{upload_id}"
            "\"). Never use any other path or ID.]"
        )
    return (
        f"\n\n[Attached image{tag}: {name}. "
        "You cannot view images; if asked "
        "about its contents, say so briefly "
        "and continue helping from the text.]"
    )


def attachments_overview(entries: List[Dict[str, str]]) -> str:
    """One-line multi-file header so the model can map files to blocks."""
    labels = {"pdf": "PDF", "csv": "CSV"}
    parts = [
        f"'{str(e.get('name', 'file'))}' "
        f"({labels.get(str(e.get('kind', '')), 'Image')})"
        for e in entries
    ]
    return (
        f"\n\n[Attached files ({len(entries)}): "
        + ", ".join(parts)
        + ". Details per file below.]"
    )


def build_chat_history(messages: List[Dict[str, Any]], limit: int = 10) -> List[BaseMessage]:
    """Convert stored messages to LangChain history (content only)."""
    history: List[BaseMessage] = []
    for msg in messages[-limit:]:
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content", ""))
        if msg.get("role") == "user":
            history.append(HumanMessage(content=content))
        else:
            history.append(AIMessage(content=content))
    return history


def _assistant_meta(tools_used: List[str], sources: List[Dict[str, str]],
                    searched: bool, deep_mode: bool, tier: str) -> Dict[str, Any]:
    """Response metadata stored on the message (locally known facts only)."""
    meta: Dict[str, Any] = {
        "mode": "deep" if deep_mode else "fast",
        "searched": bool(searched),
    }
    if tier:
        meta["model"] = tier
    names = [t for t in tools_used if isinstance(t, str) and t]
    meta["search_executed"] = "web_search" in names
    if names:
        meta["tools"] = names
    records = [dict(s) for s in sources if isinstance(s, dict)]
    if records:
        meta["sources"] = records
    return meta


def _clean_sources(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Re-validate provenance records; http(s) only, capped at 6."""
    clean: List[Dict[str, str]] = []
    for entry in records or []:
        cleaned = clean_source_record(entry)
        if cleaned is not None:
            clean.append(cleaned)
        if len(clean) >= 6:
            break
    return clean


def _resolve_attachments(ctx: UserContext,
                         upload_ids: List[str]) -> Tuple[List[Dict[str, str]], List[str]]:
    """Validate owned uploads; returns (attachment dicts, image ids).

    Raises ValueError for unknown/duplicate IDs so bad references fail
    loudly instead of silently changing the request.
    """
    attachments: List[Dict[str, str]] = []
    image_ids: List[str] = []
    seen: set = set()
    for upload_id in (upload_ids or [])[:MAX_ATTACHMENTS_PER_MESSAGE]:
        uid = str(upload_id or "")
        if not uid or uid in seen:
            continue
        try:
            meta = ctx.file_store.get_upload(uid)
        except (StorageError, FileValidationError):
            meta = None
        if meta is None:
            raise ValueError(f"Unknown attachment: {uid}")
        seen.add(uid)
        kind = str(getattr(meta, "kind", "image") or "image")
        name = str(getattr(meta, "display_name", "file") or "file")
        attachments.append({"id": uid, "kind": kind, "name": name})
        if kind not in ("pdf", "csv"):
            image_ids.append(uid)
    images = [a for a in attachments if a["kind"] not in ("pdf", "csv")]
    if len(images) > MAX_IMAGE_ATTACHMENTS:
        raise ValueError(f"At most {MAX_IMAGE_ATTACHMENTS} images per message.")
    return attachments, image_ids


def _check_limits(uid: str, deep_mode: bool) -> None:
    """Enforce chat (+deep) rate limits; raises HTTPException(429)."""
    from fastapi import HTTPException

    verdict = get_rate_limiter().check(uid, "chat")
    if not verdict.allowed:
        obs_event("ratelimit.deny", action="chat", user=uid,
                  retry_after_s=round(verdict.retry_after, 1))
        raise HTTPException(
            status_code=429,
            detail=f"Chat rate limit exceeded, retry in {verdict.retry_after:.0f}s.",
        )
    if deep_mode:
        deep_verdict = get_rate_limiter().check(uid, "deep")
        if not deep_verdict.allowed:
            obs_event("ratelimit.deny", action="deep", user=uid,
                      retry_after_s=round(deep_verdict.retry_after, 1))
            raise HTTPException(
                status_code=429,
                detail=f"Deep Mode rate limit exceeded, retry in {deep_verdict.retry_after:.0f}s.",
            )


def _load_state(store: Any) -> Tuple[List[Any], List[Any], List[str]]:
    """Load (chats, current, warnings), tolerating storage trouble."""
    try:
        stored, warnings = store.load_chats()
    except StorageError:
        stored, warnings = {"chats": [], "current": []}, []
    chats = stored.get("chats", []) if isinstance(stored, dict) else []
    current = stored.get("current", []) if isinstance(stored, dict) else []
    if not isinstance(chats, list):
        chats = []
    if not isinstance(current, list):
        current = []
    return chats, current, [str(w) for w in warnings]


def _complete_turn(ctx: UserContext, send_text: str,
                   prior_history: List[BaseMessage],
                   prior_raw: List[Dict[str, Any]],
                   image_ids: List[str], memory_notes: str,
                   project_context: str, deep_mode: bool,
                   force_search: bool,
                   active_tier: Optional[str]) -> Tuple[Dict[str, Any], str, str]:
    """Run the agent and build the assistant message (no persistence)."""
    from agent.prompts import strip_internal_reasoning

    try:
        before_ids = {m.id for m in ctx.file_store.list_outputs()}
    except Exception:
        before_ids = set()

    result = agent.answer_with_fallback(
        send_text,
        prior_history,
        first=(active_tier or None),
        memory_notes=memory_notes,
        raw_messages=prior_raw,
        deep_mode=bool(deep_mode),
        force_web_search=bool(force_search),
        image_upload_ids=image_ids,
        project_context=project_context,
    )
    output = strip_internal_reasoning(str(result.get("output", "")))
    tier = str(result.get("active_tier", "") or "")
    task_type = str(result.get("task_type", "") or "")
    tools_used = [t for t in (result.get("tools_used", []) or []) if isinstance(t, str)]
    sources = _clean_sources(result.get("sources", []) or [])

    try:
        fresh = [m for m in ctx.file_store.list_outputs() if m.id not in before_ids]
    except Exception:
        fresh = []
    new_artifacts = [
        {"id": m.id, "kind": m.kind,
         "name": str(m.display_name)[:MAX_DISPLAY_NAME_CHARS]}
        for m in fresh
    ]

    assistant_msg: Dict[str, Any] = {
        "role": "assistant",
        "content": output,
        "time": utcnow_iso(),
        **_assistant_meta(tools_used, sources, force_search, deep_mode, tier),
    }
    if new_artifacts:
        assistant_msg["artifacts"] = new_artifacts
    return assistant_msg, tier, task_type


def _memory_and_project(store: Any, project_id: Optional[str]) -> Tuple[str, str]:
    """Load memory notes + project context, tolerating storage trouble."""
    try:
        memory_notes = store.load_notes()
    except StorageError:
        memory_notes = ""
    project_context = ""
    if isinstance(project_id, str) and project_id:
        try:
            project_context = store.load_project_context(project_id)
        except Exception:
            project_context = ""
    return memory_notes, project_context


def run_chat(ctx: UserContext, content: str,
             upload_ids: Optional[List[str]] = None,
             project_id: Optional[str] = None,
             deep_mode: bool = False,
             force_search: bool = False,
             active_tier: Optional[str] = None) -> Dict[str, Any]:
    """Run one user turn end-to-end; returns send-response payload.

    Persists both messages before returning. Raises HTTPException for
    rate limits, ValueError for bad input/attachments, RuntimeError
    (user-safe message) when every tier fails.
    """
    text = str(content or "").strip()
    if not text:
        raise ValueError("Message is empty.")
    store = ctx.user_store
    _check_limits(ctx.user_id, bool(deep_mode))
    chats, current, warnings = _load_state(store)

    attachments, image_ids = _resolve_attachments(ctx, upload_ids or [])

    send_text = text
    total = len(attachments)
    if total > 1:
        send_text += attachments_overview(attachments)
    for position, attach in enumerate(attachments, start=1):
        send_text += attachment_hint(
            attach["kind"], attach["id"], attach["name"], position, total)

    user_msg: Dict[str, Any] = {
        "role": "user",
        "content": text,
        "time": utcnow_iso(),
    }
    if attachments:
        user_msg["attachments"] = attachments
    if image_ids:
        user_msg["image"] = image_ids[0]

    prior_history = build_chat_history(
        [m for m in current if isinstance(m, dict)])
    prior_raw: List[Dict[str, Any]] = [
        dict(m) for m in current if isinstance(m, dict)]
    memory_notes, project_context = _memory_and_project(store, project_id)

    assistant_msg, tier, task_type = _complete_turn(
        ctx, send_text, prior_history, prior_raw, image_ids,
        memory_notes, project_context, bool(deep_mode),
        bool(force_search), active_tier)

    current = current + [user_msg, assistant_msg]
    store.save_chats(chats, current)
    return {
        "message": assistant_msg,
        "active_tier": tier,
        "task_type": task_type,
        "warnings": warnings,
    }


def regenerate_chat(ctx: UserContext, index: int,
                    project_id: Optional[str] = None,
                    deep_mode: bool = False,
                    force_search: bool = False,
                    active_tier: Optional[str] = None) -> Dict[str, Any]:
    """Append a fresh answer to an existing assistant message.

    Rebuilds the request from the stored preceding user message
    (content + attachment hints, same shape as a fresh send) with
    history ending before it. The original answer is kept — the new
    one is appended. Raises ValueError for bad indexes/shapes.
    """
    store = ctx.user_store
    _check_limits(ctx.user_id, bool(deep_mode))
    chats, current, warnings = _load_state(store)
    msgs = [m for m in current if isinstance(m, dict)]
    if not isinstance(index, int) or not (0 <= index < len(msgs)):
        raise ValueError("Response to regenerate was not found.")
    assistant_msg = msgs[index]
    if assistant_msg.get("role") != "assistant":
        raise ValueError("Only assistant responses can be regenerated.")
    user_msg = None
    for pos in range(index - 1, -1, -1):
        if msgs[pos].get("role") == "user":
            user_msg = msgs[pos]
            user_index = pos
            break
    if user_msg is None:
        raise ValueError("Original request could not be recovered.")

    attachments = [
        a for a in (user_msg.get("attachments") or [])
        if isinstance(a, dict) and a.get("id")
    ]
    image_ids = [str(a["id"]) for a in attachments
                 if a.get("kind") not in ("pdf", "csv")]
    send_text = str(user_msg.get("content", "") or "")
    total = len(attachments)
    if total > 1:
        send_text += attachments_overview(attachments)
    for position, attach in enumerate(attachments, start=1):
        send_text += attachment_hint(
            str(attach.get("kind", "image")), str(attach.get("id", "")),
            str(attach.get("name", "file")), position, total)

    prior = msgs[:user_index]
    prior_history = build_chat_history(prior)
    prior_raw = [dict(m) for m in prior]
    memory_notes, project_context = _memory_and_project(store, project_id)

    fresh_msg, tier, task_type = _complete_turn(
        ctx, send_text, prior_history, prior_raw, image_ids,
        memory_notes, project_context, bool(deep_mode),
        bool(force_search), active_tier)

    current = current + [fresh_msg]
    store.save_chats(chats, current)
    return {
        "message": fresh_msg,
        "active_tier": tier,
        "task_type": task_type,
        "warnings": warnings,
    }


def archive_current(current: List[Dict[str, Any]],
                    project_id: Optional[str] = None,
                    chat_id: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Split the open conversation into a history record (pure logic).

    Returns (record, empty_current). Raises ValueError when empty.
    The caller owns the open conversation's id (like the Streamlit
    session's current_chat_id): pass it back to keep identity stable
    across open/archive cycles, else a fresh id is minted.
    """
    msgs = [dict(m) for m in current if isinstance(m, dict)]
    if not msgs:
        raise ValueError("Nothing to archive.")
    title = next(
        (str(m.get("content", "")) for m in msgs if m.get("role") == "user"),
        "Untitled",
    )
    record: Dict[str, Any] = {
        "id": str(chat_id) if is_valid_id(chat_id) else new_conversation_id(),
        "title": title.strip()[:MAX_CHAT_TITLE_CHARS] or "Untitled",
        "messages": msgs,
    }
    if is_valid_id(project_id):
        record["project_id"] = str(project_id)
    return record, []
