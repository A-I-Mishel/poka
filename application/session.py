"""Application session layer: stores, agent calls, and session bootstrap.

Sits between the UI (app.py, ui/*) and services/agent: it binds the
current request's user to storage, enforces chat/deep rate limits on
every send path, and initializes per-session defaults. It never renders
and never touches the filesystem directly — all persistence goes
through services.

Note: the agent entry point is called as agent.answer_with_fallback
(attribute access on the package) rather than a from-import, so test
doubles installed on the agent package stay effective.
"""

from typing import Any, Dict, List, Optional

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

import agent
from services.context import get_current_user_id
from services.files import FileStore, FileValidationError
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter
from services.storage import (
    StorageError,
    UserStore,
    is_valid_id,
    new_conversation_id,
)


def _user_store() -> UserStore:
    """Return the storage bound to the current request user."""
    user_id = get_current_user_id()
    if not user_id:
        raise StorageError("No user identity for this request.")
    return UserStore(user_id)


def _file_store() -> FileStore:
    """Return the file vault bound to the current request user."""
    user_id = get_current_user_id()
    if not user_id:
        raise StorageError("No user identity for this request.")
    return FileStore(user_id)


def build_chat_history(
    messages: List[Dict[str, str]],
    limit: int = 10,
) -> List[Any]:
    """Convert UI messages to LangChain history."""
    history: List[Any] = []

    for msg in messages[-limit:]:
        if msg["role"] == "user":
            history.append(
                HumanMessage(content=msg["content"])
            )
        else:
            history.append(
                AIMessage(content=msg["content"])
            )

    return history


def get_active_project_context() -> str:
    """Return the active project's context text, or "".

    Every condition is re-checked on each call: authenticated user,
    valid session selection, registry resolution, non-archived status,
    and a readable context file. Anything missing or unreadable yields
    "" so normal chat never breaks on context trouble.
    """
    try:
        store = _user_store()
    except StorageError:
        return ""
    try:
        active_id = st.session_state.get("active_project_id", None)
    except Exception:
        return ""
    if not isinstance(active_id, str) or not active_id:
        return ""
    try:
        record = store.get_project(active_id)
    except StorageError:
        return ""
    if not isinstance(record, dict) or record.get("archived", False):
        return ""
    try:
        return store.load_project_context(active_id)
    except Exception:
        return ""


def run_agent(
    user_input: str,
    history: Optional[List[Any]] = None,
    raw_messages: Optional[List[Dict[str, Any]]] = None,
    image_ids: Optional[List[str]] = None,
    force_web_search: Optional[bool] = None,
    project_context: Optional[str] = None,
) -> str:
    """Answer via the tool loop.

    The current input must reach the model exactly once, so callers that
    already appended it pass pre-append history explicitly. Defaults build
    from the session for flows that append after answering. Chat and Deep
    Mode rate limits are enforced here so no send path can bypass them.
    A caller that consumed a one-shot session toggle passes its captured
    value explicitly; otherwise the session value is read here.
    Project context is caller-resolved (see get_active_project_context)
    and forwarded as untrusted data; None/empty means Personal.
    """
    uid = get_current_user_id() or "anonymous"
    chat_verdict = get_rate_limiter().check(uid, "chat")
    if not chat_verdict.allowed:
        obs_event(
            "ratelimit.deny", action="chat", user=uid,
            retry_after_s=round(chat_verdict.retry_after, 1),
        )
        raise RuntimeError(
            "Chat rate limit exceeded, "
            f"retry in {chat_verdict.retry_after:.0f}s."
        )
    if bool(st.session_state.get("deep_mode", False)):
        deep_verdict = get_rate_limiter().check(uid, "deep")
        if not deep_verdict.allowed:
            obs_event(
                "ratelimit.deny", action="deep", user=uid,
                retry_after_s=round(deep_verdict.retry_after, 1),
            )
            raise RuntimeError(
                "Deep Mode rate limit exceeded, "
                f"retry in {deep_verdict.retry_after:.0f}s."
            )
    result: Dict[str, Any] = agent.answer_with_fallback(
        user_input,
        history if history is not None else build_chat_history(
            st.session_state.messages
        ),
        first=st.session_state.get("active_tier"),
        memory_notes=st.session_state.get(
            "memory_notes",
            "",
        ),
        raw_messages=(
            raw_messages if raw_messages is not None else [
                dict(m) for m in st.session_state.messages if isinstance(m, dict)
            ]
        ),
        deep_mode=bool(st.session_state.get("deep_mode", False)),
        force_web_search=(
            bool(force_web_search)
            if force_web_search is not None
            else bool(st.session_state.get("force_search", False))
        ),
        image_upload_ids=list(image_ids or []),
        project_context=str(project_context or ""),
    )

    st.session_state.active_tier = str(
        result["active_tier"]
    )

    # Tool + source provenance for the just-completed request (safe
    # values only; empty when the vision fast-path or a simple answer
    # used no tools). Callers read these immediately after their own
    # run_agent call.
    raw_tools = result.get("tools_used", [])
    st.session_state["_last_tools_used"] = [
        str(t) for t in raw_tools if isinstance(t, str)
    ][:20]
    raw_sources = result.get("sources", [])
    st.session_state["_last_sources"] = [
        dict(s) for s in raw_sources if isinstance(s, dict)
    ][:6]

    return str(result["output"])


def persist() -> None:
    """Save chats + open conversation to the current user's store.

    Storage failures are surfaced as a non-blocking warning, never silent.
    """
    try:
        _user_store().save_chats(
            st.session_state.get("chats", []),
            st.session_state.get("messages", []),
        )
    except StorageError as e:
        st.toast(f"Could not save chat history: {e}")
    except Exception:
        st.toast("Could not save chat history.")


def ensure_current_chat_id() -> str:
    """Return the open conversation's stable ID, assigning one if needed.

    Assigned at first send so a conversation has an identity from
    creation; retained across sends, edits, and retries within the open
    conversation. Never raises (falls back to a fresh ID in odd states).
    """
    try:
        current = st.session_state.get("current_chat_id", None)
    except Exception:
        current = None
    if is_valid_id(current):
        return str(current)
    fresh = new_conversation_id()
    try:
        st.session_state.current_chat_id = fresh
    except Exception:
        pass
    return fresh


def archive_current_chat() -> None:
    """Stash current messages into sidebar history with a stable ID.

    Legacy conversations without an ID receive one here (lazy
    migration: title, messages, attachments, artifacts, metadata, and
    order are untouched). The open conversation's project membership
    rides along when present. Resets open-conversation identity, so a
    caller adopting a selected chat must set its ids afterwards.
    """

    msgs: List[Dict[str, str]] = [
        dict(m)
        for m in st.session_state.messages
    ]

    if not msgs:
        return

    title: str = next(
        (
            m["content"]
            for m in msgs
            if m["role"] == "user"
        ),
        "Untitled",
    )

    record: Dict[str, Any] = {
        "id": ensure_current_chat_id(),
        "title": title.strip()[:38],
        "messages": msgs,
    }
    try:
        project_id = st.session_state.get("current_project_id", None)
    except Exception:
        project_id = None
    if is_valid_id(project_id):
        record["project_id"] = str(project_id)

    st.session_state.chats.insert(0, record)

    del st.session_state.chats[20:]

    try:
        st.session_state.current_chat_id = None
        st.session_state.current_project_id = None
    except Exception:
        pass


def _pending_list() -> List[Dict[str, Any]]:
    """Return the canonical pending-attachment list (possibly empty).

    Union of the new pending_attachments list and a legacy
    pending_attach dict (deduped by upload ID, list first), so states
    written by older sessions keep working without a restart. Writers
    below always go through _set_pending_list, which keeps both keys
    in sync. Never raises.
    """
    out: List[Dict[str, Any]] = []
    try:
        raw = st.session_state.get("pending_attachments", None)
    except Exception:
        raw = None
    if isinstance(raw, list):
        out = [
            dict(e) for e in raw
            if isinstance(e, dict) and str(e.get("upload_id", ""))
        ]
    try:
        legacy = st.session_state.get("pending_attach", None)
    except Exception:
        legacy = None
    if (
        isinstance(legacy, dict)
        and str(legacy.get("upload_id", ""))
        and all(str(e.get("upload_id", "")) != str(legacy["upload_id"])
                for e in out)
    ):
        out.append(dict(legacy))
    return out


def _set_pending_list(items: Any) -> List[Dict[str, Any]]:
    """Store the canonical pending list; mirror first entry to legacy key.

    The legacy pending_attach mirror (first entry or None) keeps older
    readers working. Returns the stored list. Never raises.
    """
    from services.limits import MAX_ATTACHMENTS_PER_MESSAGE

    clean: List[Dict[str, Any]] = []
    seen = set()
    if isinstance(items, list):
        for entry in items:
            if not isinstance(entry, dict):
                continue
            uid = str(entry.get("upload_id", ""))
            if not uid or uid in seen:
                continue
            seen.add(uid)
            clean.append(dict(entry))
    clean = clean[:MAX_ATTACHMENTS_PER_MESSAGE]
    try:
        st.session_state.pending_attachments = clean
        st.session_state.pending_attach = dict(clean[0]) if clean else None
    except Exception:
        pass
    return clean


def _attachment_append(existing: Any, entry: Any) -> tuple:
    """Append one pending attachment entry, enforcing caps and dedup.

    Pure helper (no session access): returns (updated_list, error_text).
    Duplicate upload IDs are idempotent no-ops. Limits come from
    services.limits so UI, session, and send flows share one source.
    """
    from services.limits import MAX_ATTACHMENTS_PER_MESSAGE, MAX_IMAGE_ATTACHMENTS

    clean: List[Dict[str, Any]] = [
        dict(e) for e in (existing or [])
        if isinstance(e, dict) and str(e.get("upload_id", ""))
    ]
    if not isinstance(entry, dict) or not str(entry.get("upload_id", "")):
        return clean, "That file could not be attached."
    uid = str(entry["upload_id"])
    if any(str(e.get("upload_id", "")) == uid for e in clean):
        return clean, ""
    if len(clean) >= MAX_ATTACHMENTS_PER_MESSAGE:
        return clean, (
            f"At most {MAX_ATTACHMENTS_PER_MESSAGE} attachments per message."
        )
    if str(entry.get("kind", "")) not in ("pdf", "csv"):
        images = sum(
            1 for e in clean if str(e.get("kind", "")) not in ("pdf", "csv")
        )
        if images >= MAX_IMAGE_ATTACHMENTS:
            return clean, (
                f"At most {MAX_IMAGE_ATTACHMENTS} images per message."
            )
    return clean + [dict(entry)], ""


def _stage_upload(
    uploaded: Any,
    kind: str,
    src: str,
) -> None:
    """Validate + vault an uploader/camera value, appending to pending.

    Fresh bytes are staged exactly as before (quota + validation per
    upload); the entry is APPENDED to the pending list instead of
    replacing it. Re-runs of the same widget value are deduped by mark.
    """
    if uploaded is None:
        return

    mark: List[Any] = [
        src,
        getattr(uploaded, "name", ""),
        getattr(uploaded, "size", 0),
    ]

    for staged in _pending_list():
        if isinstance(staged, dict) and staged.get("mark") == mark:
            return

    uid = get_current_user_id()
    if uid:
        upload_verdict = get_rate_limiter().check(uid, "upload")
        if not upload_verdict.allowed:
            obs_event(
                "ratelimit.deny", action="upload", user=uid,
                retry_after_s=round(upload_verdict.retry_after, 1),
            )
            st.toast(
                "Upload rate limit exceeded, "
                f"retry in {upload_verdict.retry_after:.0f}s."
            )
            return

    try:
        data: bytes = bytes(uploaded.getbuffer())
    except Exception:
        st.toast("Could not read that file.")
        return
    original = getattr(uploaded, "name", "file") or "file"
    if src == "camera":
        original = f"camera.{original.rsplit('.', 1)[-1]}" if "." in str(original) else "camera.png"
    try:
        meta = _file_store().save_upload(data, str(original))
    except (FileValidationError, StorageError) as e:
        st.toast(f"Upload rejected: {e}")
        return
    except Exception:
        st.toast("Upload rejected: unexpected storage error.")
        return

    updated, error = _attachment_append(
        _pending_list(),
        {
            "upload_id": meta.id,
            "kind": meta.kind,
            "name": meta.display_name,
            "path": meta.display_name,
            "mark": mark,
        },
    )
    if error:
        st.toast(error)
        return
    _set_pending_list(updated)

    st.rerun()


def ensure_session_defaults() -> None:
    """Initialize per-session state: chats, memory, hygiene, model tier.

    Idempotent: every block is guarded so re-runs keep existing state.
    Runs once per Streamlit script run from the page flow (app.py).
    """
    # Identity binding: the browser session can outlive the identity
    # (token sign-in, link-token switch). When the authenticated user
    # changes, drop all user-scoped state first so the previous user's
    # chats, memory, attachments, and project context can neither
    # display nor persist into the new user's vault. The _auth_user_id
    # credential itself must survive (identity derives from it).
    try:
        _current_uid = get_current_user_id()
    except Exception:
        _current_uid = None
    try:
        _bound_uid = st.session_state.get("_bound_user_id", None)
    except Exception:
        _bound_uid = None
    if _bound_uid != _current_uid:
        try:
            _keys = list(st.session_state.keys())
        except Exception:
            _keys = []
        for _key in _keys:
            if _key == "_auth_user_id" or str(_key).startswith("$$"):
                continue
            try:
                del st.session_state[_key]
            except Exception:
                pass
        try:
            st.session_state["_bound_user_id"] = _current_uid
        except Exception:
            pass

    if (
        "chats" not in st.session_state
        or "messages" not in st.session_state
    ):

        try:
            stored, store_warnings = _user_store().load_chats()
        except StorageError:
            stored, store_warnings = {"chats": [], "current": []}, []

        st.session_state.chats = (
            stored["chats"]
        )

        st.session_state.messages = (
            stored["current"]
        )

        for warning in store_warnings:
            st.toast(warning)


    if "memory_notes" not in st.session_state:
        try:
            st.session_state.memory_notes = (
                _user_store().load_notes()
            )
        except StorageError as e:
            st.session_state.memory_notes = ""
            st.toast(f"Memory notes unavailable ({e})")


    if "pruned_once" not in st.session_state:
        # One hygiene pass per browser session: drop staged uploads older
        # than 7 days that no chat message still references, and generated
        # outputs older than 30 days. Never touches other users (per-user
        # vault) or referenced files.
        st.session_state.pruned_once = True
        try:
            referenced: set = set()
            for chat in list(st.session_state.get("chats", [])):
                for m in (chat.get("messages", []) if isinstance(chat, dict) else []):
                    for a in (m.get("attachments", []) if isinstance(m, dict) else []):
                        if isinstance(a, dict) and a.get("id"):
                            referenced.add(str(a["id"]))
            for m in st.session_state.get("messages", []):
                if isinstance(m, dict):
                    for a in (m.get("attachments", []) or []):
                        if isinstance(a, dict) and a.get("id"):
                            referenced.add(str(a["id"]))
            _file_store().prune_stale_uploads(7, referenced)
            _file_store().prune_stale_outputs()
        except Exception:
            pass


    if "pending_attach" not in st.session_state:
        st.session_state.pending_attach = None


    if "pending_attachments" not in st.session_state:
        st.session_state.pending_attachments = []


    if "force_search" not in st.session_state:
        st.session_state.force_search = False

    if "deep_mode" not in st.session_state:
        st.session_state.deep_mode = False

    if "confirm_clean" not in st.session_state:
        st.session_state.confirm_clean = False


    if "attach_menu" not in st.session_state:
        st.session_state.attach_menu = None


    if "composer_key" not in st.session_state:
        st.session_state.composer_key = 0


    if "current_chat_id" not in st.session_state:
        st.session_state.current_chat_id = None


    if "current_project_id" not in st.session_state:
        st.session_state.current_project_id = None


    if "active_project_id" not in st.session_state:
        st.session_state.active_project_id = None


    if "show_attach_menu" not in st.session_state:
        st.session_state.show_attach_menu = False

    if "selected_brief_id" not in st.session_state:
        st.session_state.selected_brief_id = None

    if "sidebar_view" not in st.session_state:
        st.session_state.sidebar_view = None

    if "more_open" not in st.session_state:
        st.session_state.more_open = False

    if "selected_workflow" not in st.session_state:
        st.session_state.selected_workflow = None

    if "workflow_research_question" not in st.session_state:
        st.session_state.workflow_research_question = ""

    if "workflow_doc_question" not in st.session_state:
        st.session_state.workflow_doc_question = ""

    if "workflow_last_research" not in st.session_state:
        st.session_state.workflow_last_research = None

    if "workflow_last_analysis" not in st.session_state:
        st.session_state.workflow_last_analysis = None


    if "active_tier" not in st.session_state:

        # Lazy health detection: start on the first configured tier without
        # probing every provider at load. The cascade corrects on first use.
        from config import TIER_GETTERS

        configured: List[str] = [
            n
            for n, g in TIER_GETTERS
            if g() is not None
        ]

        if not configured:

            st.error(
                "No LLM available. Add "
                "OPENCODE_API_KEY or "
                "GEMINI_API_KEY to .env"
            )

            st.info(
                "Add at least one key to `.env` "
                "(OPENCODE_API_KEY or "
                "GEMINI_API_KEY), or set them "
                "in Streamlit Cloud Secrets, "
                "then rerun the app."
            )

            # No provider credentials (e.g. CI/test runs without keys):
            # keep rendering with an explicit offline tier instead of
            # stopping, so the UI stays testable. Any send attempt then
            # fails gracefully through the normal cascade error path.
            # The cascade self-corrects active_tier on first success.
            st.session_state.active_tier = (
                "No LLM configured"
            )

        else:

            st.session_state.active_tier = (
                configured[0]
            )
