"""Streamlit UI for Poka -- indigo dark theme, no emojis."""

import html
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st
import streamlit.components.v1 as components
from langchain_core.messages import AIMessage, HumanMessage

from agent import answer_with_fallback
from services.auth import AuthRequired, authenticate, verify_access_token
from services.context import get_current_user_id, set_current_user_id
from services.files import FileStore, FileValidationError
from services.ratelimit import get_rate_limiter
from services.storage import StorageError, UserStore
from services.timeutil import format_local, utcnow_iso, utcnow_stamp
import memory_engine


st.set_page_config(
    page_title="Poka",
    page_icon="*",
    layout="centered",
)


# ============== REQUEST IDENTITY (set fresh on every run) ==============
try:
    _auth = authenticate()
    set_current_user_id(_auth.identity.id)
    _USER_ID: str = _auth.identity.id
except AuthRequired as _auth_error:
    set_current_user_id(None)
    _USER_ID = ""
    st.markdown(
        '<div style="text-align:center;padding:48px 20px 12px;">'
        '<h1 class="brand-title">Poka</h1>'
        '<p style="color:#8b8b9e;font-size:14px;">This app is private.</p>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(str(_auth_error))
    _token_input = st.text_input("Access token", type="password", key="auth-token")
    if st.button("Sign in", key="auth-go"):
        _verified = verify_access_token(_token_input)
        if _verified:
            st.session_state["_auth_user_id"] = _verified
            st.rerun()
        else:
            st.error("Invalid token.")
    st.stop()
except Exception:
    set_current_user_id(None)
    _USER_ID = ""


def _user_store() -> UserStore:
    """Return the storage bound to the current request user."""
    if not _USER_ID:
        raise StorageError("No user identity for this request.")
    return UserStore(_USER_ID)


def _file_store() -> FileStore:
    """Return the file vault bound to the current request user."""
    if not _USER_ID:
        raise StorageError("No user identity for this request.")
    return FileStore(_USER_ID)


try:
    if _USER_ID:
        memory_engine.set_memory_dir(str(UserStore(_USER_ID).root))
except Exception:
    pass


# ============================================================
# THEME
# ============================================================
from ui.theme import apply_theme


apply_theme()


# ============================================================
# HELPERS
# ============================================================

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
        raise RuntimeError(
            "Chat rate limit exceeded, "
            f"retry in {chat_verdict.retry_after:.0f}s."
        )
    if bool(st.session_state.get("deep_mode", False)):
        deep_verdict = get_rate_limiter().check(uid, "deep")
        if not deep_verdict.allowed:
            raise RuntimeError(
                "Deep Mode rate limit exceeded, "
                f"retry in {deep_verdict.retry_after:.0f}s."
            )
    result: Dict[str, Any] = answer_with_fallback(
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

    if _USER_ID:
        upload_verdict = get_rate_limiter().check(_USER_ID, "upload")
        if not upload_verdict.allowed:
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


def _format_time(iso_str: str) -> str:
    """Format an ISO timestamp in local time, "" when missing."""
    return format_local(iso_str)


def _highlight_query(text: str, query: str) -> str:
    """Wrap case-insensitive query matches in <mark>, preserving structure.

    Code fences, inline code, images, and links are never touched so
    highlighting cannot corrupt Markdown formatting or URLs.
    """
    if not query.strip():
        return text
    parts = re.split(
        r"(```.*?```|`[^`\n]+`|!\[[^\]]*\]\([^)]*\)|\[[^\]]*\]\([^)]*\))",
        text,
        flags=re.DOTALL,
    )
    out: List[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1 or not part.strip():
            out.append(part)
            continue
        out.append(
            re.sub(
                re.escape(query),
                lambda m: f'<mark class="search-hit">{m.group(0)}</mark>',
                part,
                flags=re.IGNORECASE,
            )
        )
    return "".join(out)


def _export_chat_to_markdown(messages: List[Dict[str, Any]]) -> str:
    """Render the conversation as a Markdown document for download."""
    lines: List[str] = [
        "# Poka Chat Export\n",
        f"Exported: {utcnow_stamp('%Y-%m-%d %H:%M')}\n\n",
    ]
    for m in messages:
        role = "You" if m.get("role") == "user" else "Poka"
        time_str = _format_time(str(m.get("time", "")))
        stamp = f" — {time_str}" if time_str else ""
        lines.append(f"## {role}{stamp}\n\n{m.get('content', '')}\n\n---\n\n")
    return "".join(lines)


def _show_typing() -> Any:
    """Show the three-dot typing indicator; caller empties the box."""
    box = st.empty()
    box.markdown(
        '<div class="typing-indicator"><span></span><span></span><span></span></div>',
        unsafe_allow_html=True,
    )
    return box


def render_assistant_response(
    user_text: str,
) -> None:
    """Append user text and render assistant reply."""

    attach = st.session_state.pop(
        "pending_attach",
        None,
    )

    # One-shot toggle: the agent enforces the search as policy (see run_agent).
    st.session_state.force_search = False

    send_text: str = user_text

    image_path: Any = None
    image_ids: List[str] = []
    attachments: List[Dict[str, str]] = []

    if isinstance(attach, dict):

        kind: str = str(
            attach.get("kind", "")
        )
        upload_id: str = str(attach.get("upload_id", ""))
        disp_name: str = str(attach.get("name", "file"))
        if upload_id:
            attachments.append({"id": upload_id, "kind": kind, "name": disp_name})

        if kind == "pdf":

            send_text += (
                f"\n\n[Attached PDF '{disp_name}' with upload ID: {upload_id}. "
                "To read it, call read_pdf(upload_id=\""
                f"{upload_id}"
                "\"). Never use any other path or ID.]"
            )

        elif kind == "csv":

            send_text += (
                f"\n\n[Attached CSV '{disp_name}' with upload ID: {upload_id}. "
                "To analyze it, call analyze_csv(upload_id=\""
                f"{upload_id}"
                "\"). Never use any other path or ID.]"
            )

        else:

            try:
                resolved = _file_store().resolve_upload(upload_id) if upload_id else None
            except (StorageError, FileValidationError):
                resolved = None
            image_path = str(resolved) if resolved is not None else None
            if upload_id:
                image_ids.append(upload_id)

            send_text += (
                f"\n\n[Attached image: {disp_name}. "
                "You cannot view images; if asked "
                "about its contents, say so briefly "
                "and continue helping from the text.]"
            )

    user_msg: Dict[str, Any] = {
        "role": "user",
        "content": user_text,
        "time": utcnow_iso(),
    }
    if attachments:
        user_msg["attachments"] = attachments

    if image_path:
        user_msg["image"] = str(image_path)

    prior_history = build_chat_history(st.session_state.messages)
    prior_raw: List[Dict[str, Any]] = [
        dict(m) for m in st.session_state.messages if isinstance(m, dict)
    ]

    st.session_state.messages.append(
        user_msg
    )

    with st.chat_message("user"):

        if (
            image_path
            and os.path.exists(
                str(image_path)
            )
        ):
            st.image(
                str(image_path),
                width=280,
            )

        st.markdown(user_text)

    with st.chat_message("assistant"):

        typing_box = _show_typing()

        try:

            request_started: float = time.time()

            output: str = run_agent(
                send_text,
                history=prior_history,
                raw_messages=prior_raw,
                image_ids=image_ids,
            )

            typing_box.empty()

            st.markdown(output)

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": output,
                    "time": utcnow_iso(),
                }
            )

            st.session_state.pop("last_failed", None)

            persist()

            try:
                fresh_files = [
                    m for m in _file_store().list_outputs()
                    if m.created >= request_started
                ]
            except StorageError:
                fresh_files = []
            for meta in fresh_files:
                file_bytes = _file_store().read_output(meta.id)
                if file_bytes is None:
                    continue
                st.download_button(
                    f"Download {meta.display_name}",
                    file_bytes,
                    file_name=meta.display_name,
                    key=(
                        f"dl-{meta.id}-"
                        f"{len(st.session_state.messages)}"
                    ),
                )

        except Exception as e:

            typing_box.empty()

            st.session_state.last_failed = send_text

            st.error(
                f"Error: {e}"
            )


def _retry_last() -> None:
    """Re-run the last failed request without duplicating the user message."""
    send_text = st.session_state.pop("last_failed", None)
    if not send_text:
        return
    prior = list(st.session_state.messages)
    retry_history = build_chat_history(prior[:-1] if prior else [])
    retry_raw: List[Dict[str, Any]] = [
        dict(m) for m in (prior[:-1] if prior else []) if isinstance(m, dict)
    ]
    with st.chat_message("assistant"):
        typing_box = _show_typing()
        try:
            output: str = run_agent(
                str(send_text),
                history=retry_history,
                raw_messages=retry_raw,
            )
            typing_box.empty()
            st.markdown(output)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": output,
                    "time": utcnow_iso(),
                }
            )
            persist()
        except Exception as e:
            typing_box.empty()
            st.session_state.last_failed = send_text
            st.error(f"Error: {e}")
            st.rerun()


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


def tier_status(
    tier_name: str,
) -> tuple:
    """Map a tier name to badge class and marker."""

    if tier_name == "Muse Spark 1.3":
        return (
            "online",
            "●",
        )

    if (
        tier_name.startswith("Gemini")
        or tier_name.startswith("Nemotron")
    ):
        return (
            "fallback",
            "◐",
        )

    return (
        "offline",
        "○",
    )


# ============================================================
# SESSION STATE
# ============================================================

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
    except StorageError:
        st.session_state.memory_notes = ""


if "pruned_once" not in st.session_state:
    # One hygiene pass per browser session: drop staged uploads older
    # than 7 days that no chat message still references. Never touches
    # other users (per-user vault) or referenced files.
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

        st.stop()

    st.session_state.active_tier = (
        configured[0]
    )


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown(
        '<div style="text-align: center; '
        'padding: 24px 0 16px;">'
        '<h1 class="brand-title">Poka</h1>'
        '<p style="color: #8b8b9e; '
        'font-size: 13px; margin-top: 6px;">'
        'Multi-purpose AI Assistant'
        '</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    model_name: str = str(
        st.session_state.active_tier
    )

    status_class, status_icon = tier_status(
        model_name
    )

    st.markdown(
        '<div style="text-align: center; '
        'margin-bottom: 24px;">'
        f'<span class="status-badge '
        f'status-{status_class}">'
        f'{status_icon} {model_name}'
        '</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown("<hr style='border-color:#27273a;margin:16px 0;'>", unsafe_allow_html=True)
    st.markdown('<p class="section-label">Mode</p>', unsafe_allow_html=True)
    st.toggle("Deep Mode", key="deep-mode")
    mode_color = "#6366f1" if st.session_state.deep_mode else "#8b8b9e"
    mode_label = "Deep" if st.session_state.deep_mode else "Fast"
    st.markdown(
        f'<p style="color:{mode_color};font-size:12px;'
        'font-weight:600;text-align:center;">'
        f"{mode_label} Mode Active</p>",
        unsafe_allow_html=True,
    )

    if st.button(
        "+ New chat",
        type="primary",
        key="new-chat",
    ):

        archive_current_chat()

        st.session_state.messages = []

        persist()

        st.rerun()


    search_q: str = st.text_input(
        "Search chat",
        placeholder="Find in conversation...",
        label_visibility="collapsed",
        key="chat-search",
    )
    if search_q.strip():
        match_count: int = sum(
            1
            for m in st.session_state.messages
            if search_q.lower() in str(m.get("content", "")).lower()
        )
        st.caption(f"{match_count} matches")

    if st.session_state.chats:

        st.markdown(
            '<p class="section-label">Chats</p>',
            unsafe_allow_html=True,
        )

        for i, chat in enumerate(
            list(st.session_state.chats)
        ):

            chat_title: str = str(
                chat.get(
                    "title",
                    "Untitled",
                )
            )[:34] or "Untitled"

            title_col, pencil_col = st.columns([4, 1])
            with title_col:
                if st.button(
                    chat_title,
                    key=f"hist-{i}",
                ):

                    selected: Dict[str, Any] = (
                        st.session_state.chats.pop(i)
                    )

                    archive_current_chat()

                    st.session_state.messages = (
                        selected["messages"]
                    )

                    persist()

                    st.rerun()
            with pencil_col:
                if st.button("✎", key=f"rename-{i}"):
                    st.session_state.renaming_idx = i
                    st.rerun()

            if st.session_state.get("renaming_idx") == i:
                new_title: str = st.text_input(
                    "Rename chat",
                    value=str(chat.get("title", "")),
                    key=f"rename-box-{i}",
                )
                save_col, cancel_col = st.columns(2)
                if save_col.button("Save", key=f"rename-save-{i}"):
                    st.session_state.chats[i]["title"] = (
                        new_title.strip()[:38] or chat_title
                    )
                    st.session_state.renaming_idx = None
                    persist()
                    st.rerun()
                if cancel_col.button("Cancel", key=f"rename-cancel-{i}"):
                    st.session_state.renaming_idx = None
                    st.rerun()


    with st.expander("Memory"):

        st.caption(
            "Things Poka should always remember."
        )

        notes_in = st.text_area(
            "Memory notes",
            value=st.session_state.get(
                "memory_notes",
                "",
            ),
            height=120,
            label_visibility="collapsed",
            key="memory-box",
        )

        if st.button(
            "Save memory",
            key="save-memory",
        ):

            try:
                _user_store().save_notes(notes_in)
            except StorageError as e:
                st.toast(f"Could not save memory: {e}")
            else:
                st.session_state.memory_notes = (
                    notes_in
                )

                st.toast("Memory saved")

        forget_in = st.text_input(
            "Forget a remembered fact",
            placeholder="name, preference, or #",
            label_visibility="collapsed",
            key="forget-box",
        )
        if st.button(
            "Forget",
            key="forget-memory",
        ):
            if memory_engine.delete_memory_fact(forget_in):
                st.toast("Forgotten.")
            else:
                st.toast("Nothing matched that.")
            st.rerun()


    with st.expander(
        "Files & stats",
        expanded=False,
    ):

        st.markdown(
            '<p class="section-label">'
            'Generated Files'
            '</p>',
            unsafe_allow_html=True,
        )

        try:
            owned_files = _file_store().list_outputs()
        except StorageError:
            owned_files = []

        if owned_files:

            for meta in owned_files[:5]:

                st.markdown(
                    f'<div class="file-card">'
                    f'{meta.display_name}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                file_bytes = _file_store().read_output(meta.id)
                if file_bytes is not None:
                    st.download_button(
                        "Get file",
                        file_bytes,
                        file_name=meta.display_name,
                        key=f"side-dl-{meta.id}",
                    )

        else:

            st.markdown(
                '<p style="color: #555; '
                'font-size: 12px; '
                'text-align: center;">'
                'No files yet'
                '</p>',
                unsafe_allow_html=True,
            )


        st.markdown(
            '<p class="section-label">Stats</p>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="stats-box">'
            '<div style="display: flex; '
            'justify-content: space-between; '
            'margin-bottom: 10px;">'
            '<span style="color: #8b8b9e; '
            'font-size: 13px;">Messages</span>'
            f'<span style="color: #f1f1f4; '
            f'font-weight: 600;">'
            f'{len(st.session_state.messages)}'
            '</span>'
            '</div>'
            '<div style="display: flex; '
            'justify-content: space-between; '
            'margin-bottom: 10px;">'
            '<span style="color: #8b8b9e; '
            'font-size: 13px;">Files</span>'
            f'<span style="color: #f1f1f4; '
            f'font-weight: 600;">'
            f'{len(owned_files)}'
            '</span>'
            '</div>'
            '<div style="display: flex; '
            'justify-content: space-between;">'
            '<span style="color: #8b8b9e; '
            'font-size: 13px;">Active</span>'
            f'<span style="color: #6366f1; '
            f'font-weight: 600; '
            f'font-size: 12px;">'
            f'{model_name}'
            '</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.session_state.messages:
            st.download_button(
                "Export chat",
                _export_chat_to_markdown(st.session_state.messages),
                file_name=f"poka_chat_{utcnow_stamp()}.md",
                mime="text/markdown",
                key="export-chat",
            )

        if st.button("Clean old files", key="clean-files"):
            st.session_state.confirm_clean = True
            st.rerun()
        if st.session_state.get("confirm_clean"):
            st.caption("Delete ALL generated PPTX/DOCX files?")
            yes_col, no_col = st.columns(2)
            if yes_col.button("Yes", key="clean-yes"):
                try:
                    removed = _file_store().delete_all_outputs()
                except StorageError:
                    removed = 0
                st.session_state.confirm_clean = False
                st.toast(f"Files cleaned ({removed} removed)")
                st.rerun()
            if no_col.button("Cancel", key="clean-no"):
                st.session_state.confirm_clean = False
                st.rerun()


# ============================================================
# MAIN
# ============================================================

if not st.session_state.messages:

    st.markdown(
        '<div class="hero">'
        '<h1>What can I help you with?</h1>'
        '<p>'
        'Presentations, documents, research, '
        'data analysis — just ask.'
        '</p>'
        '</div>',
        unsafe_allow_html=True,
    )


# Render conversation
search_text: str = str(st.session_state.get("chat-search", "") or "")
for idx, msg in enumerate(st.session_state.messages):

    with st.chat_message(msg["role"]):

        if (
            msg.get("image")
            and os.path.exists(
                str(msg["image"])
            )
        ):
            st.image(
                str(msg["image"]),
                width=280,
            )

        st.markdown(
            _highlight_query(str(msg.get("content", "")), search_text)
        )
        msg_time: str = _format_time(str(msg.get("time", "")))
        if msg_time:
            st.caption(msg_time)

    if isinstance(msg, dict) and msg.get("role") == "user":
        with st.container(key=f"msgrow-{idx}"):
            if st.button("Edit", key=f"edit-{idx}"):
                old_text: str = str(msg.get("content", ""))
                old_atts = msg.get("attachments")
                restored = None
                if isinstance(old_atts, list):
                    for candidate in old_atts:
                        if isinstance(candidate, dict) and candidate.get("id"):
                            restored = {
                                "upload_id": str(candidate["id"]),
                                "kind": str(candidate.get("kind", "image")),
                                "name": str(candidate.get("name", "file")),
                                "mark": ["restored", str(candidate["id"])],
                            }
                            break
                st.session_state.messages = st.session_state.messages[:idx]
                st.session_state[
                    f"composer_input_{st.session_state.composer_key}"
                ] = old_text
                st.session_state.pending_attach = restored
                persist()
                st.rerun()


# ============================================================
# ATTACHMENT STATUS
# ============================================================

pending = st.session_state.get(
    "pending_attach"
)

if isinstance(pending, dict):
    chip_text, chip_x = st.columns(
        [5, 1]
    )

    chip_text.markdown(
        '<div class="attach-chip">'
        'Attached: '
        + html.escape(
            str(
                pending.get(
                    "name",
                    "file",
                )
            )
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    if chip_x.button(
        "x",
        key="rm-attach",
    ):

        st.session_state.pending_attach = None

        st.rerun()

elif st.session_state.get(
    "force_search"
):

    st.caption(
        "Web search will be used for the next message."
    )


# ============================================================
# CUSTOM COMPOSER
# ============================================================

with st.container(
    key="composer"
):

    col_plus, col_input, col_send = st.columns(
        [0.7, 8.3, 0.8],
        gap="small",
        vertical_alignment="center",
    )


    # --------------------------------------------------------
    # PLUS BUTTON
    # --------------------------------------------------------

    with col_plus:

        plus_clicked = st.button(
            "+",
            key="composer_plus",
            help="Attachments and tools",
        )


    # --------------------------------------------------------
    # INPUT
    # --------------------------------------------------------

    with col_input:

        field_key = (
            f"composer_input_"
            f"{st.session_state.composer_key}"
        )

        st.text_input(
            "Message",
            placeholder="Type your message...",
            label_visibility="collapsed",
            key=field_key,
        )


    # --------------------------------------------------------
    # SEND
    # --------------------------------------------------------

    with col_send:

        send_clicked = st.button(
            "↑",
            key="composer_send",
        )


# Enter key inside the composer input clicks Send (text_input alone
# only commits its value on Enter without submitting anything).
# Also keeps the chat pinned to the bottom while new messages arrive.
components.html(
    """
<script>
(function () {
    const win = window.parent;
    const doc = win.document;

    /* --- Enter-to-send (rebound to the fresh input after every send,
       since each send recreates the input with a new widget key) --- */
    const scope = doc.querySelector(".st-key-composer")
        || doc.querySelector('section[data-testid="stMain"]');
    if (scope) {
        const input = scope.querySelector('div[data-testid="stTextInput"] input');
        if (input && !input.dataset.enterBound) {
            input.dataset.enterBound = "1";
            input.setAttribute("autocomplete", "off");
            input.setAttribute("autocapitalize", "off");
            input.setAttribute("autocorrect", "off");
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
                    e.preventDefault();
                    const box = input.closest(".st-key-composer") || scope;
                    const btns = box.querySelectorAll("button");
                    const send = btns[btns.length - 1];
                    if (send) send.click();
                }
            });
        }
    }

    /* --- auto-scroll follower (bound once per page) --- */
    if (doc.__pokaScrollBound) return;
    doc.__pokaScrollBound = true;

    function pageScroller() {
        const docEl = doc.scrollingElement || doc.documentElement;
        const section = doc.querySelector('section[data-testid="stMain"]');
        const cands = [docEl, doc.body, section];
        for (const el of cands) {
            if (el && el.scrollHeight > el.clientHeight + 10) return el;
        }
        return docEl || doc.body;
    }
    function nearBottom() {
        try {
            const y = win.scrollY || win.pageYOffset || 0;
            const h = doc.body ? doc.body.scrollHeight : 0;
            if (h > win.innerHeight + 10) {
                return h - y - win.innerHeight < 180;
            }
        } catch (err) { /* fall through to element check */ }
        const el = pageScroller();
        if (!el) return true;
        return el.scrollHeight - el.scrollTop - el.clientHeight < 180;
    }
    function goBottom(smooth) {
        const el = pageScroller();
        if (!el) return;
        try {
            if (smooth && el.scrollTo) {
                el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
                return;
            }
        } catch (err) { /* fall through */ }
        el.scrollTop = el.scrollHeight;
    }

    let wasNear = true;
    try {
        win.addEventListener("scroll", function () { wasNear = nearBottom(); }, true);
    } catch (err) { /* ignore */ }
    setTimeout(function () { goBottom(false); }, 400);

    new MutationObserver(function (muts) {
        let hasChat = false;
        for (const m of muts) {
            const nodes = m.addedNodes || [];
            for (const n of nodes) {
                if (n.nodeType !== 1) continue;
                try {
                    if (n.matches('[data-testid="stChatMessage"]') || n.querySelector('[data-testid="stChatMessage"]')) {
                        hasChat = true;
                        break;
                    }
                } catch (err) { /* ignore */ }
            }
            if (hasChat) break;
        }
        if (hasChat && wasNear) {
            goBottom(true);
            setTimeout(function () { goBottom(false); }, 450);
        }
        try { wasNear = nearBottom(); } catch (err) { /* ignore */ }
    }).observe(doc.body, { childList: true, subtree: true });

    /* --- Copy buttons on assistant messages (hover to reveal) --- */
    function armCopyButtons() {
        const nodes = doc.querySelectorAll('div[data-testid="stChatMessage"]');
        for (const node of nodes) {
            if (node.dataset.pokaActions) continue;
            const content = node.querySelector('div[data-testid="stChatMessageContent"]');
            if (!content) continue;
            node.dataset.pokaActions = "1";
            const btn = doc.createElement("button");
            btn.textContent = "Copy";
            btn.className = "poka-copy";
            btn.type = "button";
            btn.addEventListener("click", function (ev) {
                ev.stopPropagation();
                const text = content.innerText || content.textContent || "";
                const done = function () {
                    btn.textContent = "Copied";
                    setTimeout(function () { btn.textContent = "Copy"; }, 1200);
                };
                const fallbackCopy = function () {
                    try {
                        const ta = doc.createElement("textarea");
                        ta.value = text;
                        ta.style.position = "fixed";
                        ta.style.opacity = "0";
                        doc.body.appendChild(ta);
                        ta.select();
                        doc.execCommand("copy");
                        doc.body.removeChild(ta);
                        done();
                    } catch (err) {
                        btn.textContent = "Failed";
                    }
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(done, fallbackCopy);
                } else {
                    fallbackCopy();
                }
            });
            node.appendChild(btn);
        }
    }
    armCopyButtons();
    new MutationObserver(function () { armCopyButtons(); }).observe(doc.body, { childList: true, subtree: true });
})();
</script>
""",
    height=0,
)


# ============================================================
# PLUS MENU
# ============================================================

if plus_clicked:

    st.session_state.show_attach_menu = (
        not st.session_state.get(
            "show_attach_menu",
            False,
        )
    )

    st.rerun()


if st.session_state.get(
    "show_attach_menu",
    False,
):

    with st.container(
        key="attachment-menu"
    ):

        if st.button(
            "Add files or photos",
            key="menu-files",
        ):

            st.session_state.attach_menu = (
                None
                if st.session_state.attach_menu
                == "files"
                else "files"
            )

            st.rerun()


        if st.session_state.attach_menu == "files":

            doc = st.file_uploader(
                "Add files or photos",
                type=[
                    "pdf",
                    "csv",
                    "png",
                    "jpg",
                    "jpeg",
                ],
                label_visibility="collapsed",
                key="composer_file_uploader",
            )

            if doc is not None:

                ext: str = (
                    str(doc.name)
                    .lower()
                    .rsplit(".", 1)[-1]
                )

                if ext == "pdf":
                    doc_kind = "pdf"

                elif ext == "csv":
                    doc_kind = "csv"

                else:
                    doc_kind = "image"

                _stage_upload(
                    doc,
                    doc_kind,
                    "menu",
                )


        if st.button(
            "Take a photo",
            key="menu-camera",
        ):

            st.session_state.attach_menu = (
                None
                if st.session_state.attach_menu
                == "camera"
                else "camera"
            )

            st.rerun()


        if st.session_state.attach_menu == "camera":

            shot = st.camera_input(
                "Take a photo",
                label_visibility="collapsed",
                key="composer_camera",
            )

            _stage_upload(
                shot,
                "image",
                "camera",
            )


        search_on: bool = bool(
            st.session_state.get(
                "force_search",
                False,
            )
        )

        if st.button(
            (
                "✓ "
                if search_on
                else ""
            )
            + "Web search",
            key="menu-search",
        ):

            st.session_state.force_search = (
                not search_on
            )

            st.session_state.show_attach_menu = (
                False
            )

            st.rerun()


# ============================================================
# SEND MESSAGE
# ============================================================

if send_clicked:

    field_key = (
        f"composer_input_"
        f"{st.session_state.composer_key}"
    )

    text: str = str(
        st.session_state.get(
            field_key,
            "",
        )
    ).strip()

    if text:

        st.session_state.pending_prompt = text

        st.session_state.composer_key += 1

        st.rerun()


# ============================================================
# PROCESS PENDING MESSAGE
# ============================================================

pending_prompt = st.session_state.pop(
    "pending_prompt",
    None,
)

if pending_prompt:

    render_assistant_response(
        str(pending_prompt)
    )


# Retry lives here (after send processing) so a failure in this same run
# immediately shows both the error above and the Retry button below.
if st.session_state.pop("do_retry", False):
    _retry_last()

if st.session_state.get("last_failed"):
    if st.button("Retry", key="retry-main"):
        st.session_state.do_retry = True
        st.rerun()


# ============================================================
# FOOTER
# ============================================================

st.markdown(
    f'<div style="text-align: center; '
    f'padding: 24px; color: #555; '
    f'font-size: 12px;">'
    f'<p>Poka v1.0 — Powered by '
    f'{model_name}</p>'
    f'</div>',
    unsafe_allow_html=True,
)
