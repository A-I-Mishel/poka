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
from services.storage import StorageError, UserStore


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


def run_agent(
    user_input: str,
    history: Optional[List[Any]] = None,
    raw_messages: Optional[List[Dict[str, Any]]] = None,
    image_ids: Optional[List[str]] = None,
) -> str:
    """Answer via the tool loop.

    The current input must reach the model exactly once, so callers that
    already appended it pass pre-append history explicitly. Defaults build
    from the session for flows that append after answering. Chat and Deep
    Mode rate limits are enforced here so no send path can bypass them.
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
        force_web_search=bool(st.session_state.get("force_search", False)),
        image_upload_ids=list(image_ids or []),
    )

    st.session_state.active_tier = str(
        result["active_tier"]
    )

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


def archive_current_chat() -> None:
    """Stash current messages into sidebar history."""

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

    st.session_state.chats.insert(
        0,
        {
            "title": title.strip()[:38],
            "messages": msgs,
        },
    )

    del st.session_state.chats[20:]


def _stage_upload(
    uploaded: Any,
    kind: str,
    src: str,
) -> None:
    """Validate + vault an uploader/camera value as the pending attachment.

    Args:
        uploaded: The UploadedFile value, or None.
        kind: Attachment kind: "pdf", "csv", or "image".
        src: Where it came from: "menu" or "camera".
    """
    if uploaded is None:
        return

    mark: List[Any] = [
        src,
        getattr(uploaded, "name", ""),
        getattr(uploaded, "size", 0),
    ]

    pending = st.session_state.get(
        "pending_attach"
    )

    if (
        isinstance(pending, dict)
        and pending.get("mark") == mark
    ):
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

    st.session_state.pending_attach = {
        "upload_id": meta.id,
        "kind": meta.kind,
        "name": meta.display_name,
        "path": meta.display_name,
        "mark": mark,
    }

    st.rerun()


def ensure_session_defaults() -> None:
    """Initialize per-session state: chats, memory, hygiene, model tier.

    Idempotent: every block is guarded so re-runs keep existing state.
    Runs once per Streamlit script run from the page flow (app.py).
    """
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


    if "show_attach_menu" not in st.session_state:
        st.session_state.show_attach_menu = False


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
