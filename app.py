"""Streamlit UI for Poka -- indigo dark theme, no emojis."""

import glob
import html
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

from agent import answer_with_fallback, probe_live_tier
from store import load_memory_notes, load_store, save_memory_notes, save_store

st.set_page_config(page_title="Poka", page_icon="*", layout="centered")

# ============== THEME ==============
THEME_CSS: str = """
* {
    font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
.stApp {
    background: #0a0a0f;
    color: #f1f1f4;
}
section[data-testid="stMain"] .block-container,
div[data-testid="stMainBlockContainer"] {
    max-width: 48rem;
}
header[data-testid="stHeader"] {
    background: rgba(10, 10, 15, 0.0);
}
header[data-testid="stHeader"] button {
    color: #8b8b9e;
}
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #0a0a0f; }
::-webkit-scrollbar-thumb { background: #27273a; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #6366f1; }

/* ---- brand + hero ---- */
.brand-title {
    font-size: 34px;
    font-weight: 700;
    background: linear-gradient(135deg, #f1f1f4, #6366f1);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0;
}
.hero {
    text-align: center;
    padding: 40px 20px 8px;
}
.hero h1 {
    font-size: 38px;
    font-weight: 700;
    margin: 0;
    color: #f1f1f4;
}
.hero p {
    color: #8b8b9e;
    font-size: 16px;
    margin-top: 10px;
}
.section-label {
    color: #8b8b9e;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    font-weight: 600;
    margin: 1.1rem 0 0.5rem;
}

/* ---- status badge ---- */
.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 500;
}
.status-online { background: rgba(16, 185, 129, 0.12); color: #10b981; }
.status-fallback { background: rgba(245, 158, 11, 0.12); color: #f59e0b; }
.status-offline { background: rgba(239, 68, 68, 0.12); color: #ef4444; }

/* ---- chat bubbles (built on st.chat_message so markdown renders) ---- */
@keyframes slideRight {
    from { opacity: 0; transform: translateX(25px); }
    to { opacity: 1; transform: translateX(0); }
}
@keyframes slideLeft {
    from { opacity: 0; transform: translateX(-25px); }
    to { opacity: 1; transform: translateX(0); }
}
div[data-testid="stChatMessage"] {
    background: transparent;
    border: none;
    padding: 0.4rem 0;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageAvatarUser"] {
    display: none;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] {
    background: #6366f1;
    color: #FFFFFF;
    padding: 14px 20px;
    border-radius: 16px 16px 4px 16px;
    margin-left: auto;
    max-width: 75%;
    box-shadow: 0 4px 20px rgba(99, 102, 241, 0.25);
    animation: slideRight 0.3s ease;
    font-size: 15px;
    line-height: 1.6;
}
div[data-testid="stChatMessageAvatarAssistant"] {
    display: none;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] {
    background: #1a1a2e;
    color: #f1f1f4;
    padding: 14px 20px;
    border-radius: 16px 16px 16px 4px;
    border: 1px solid #27273a;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
    animation: slideLeft 0.3s ease;
    font-size: 15px;
    line-height: 1.6;
    max-width: 100%;
}
div[data-testid="stChatMessageContent"] a {
    color: #818cf8;
}
div[data-testid="stChatMessageContent"] code {
    background: #12121a;
    border: 1px solid #27273a;
    border-radius: 6px;
    padding: 0.1rem 0.35rem;
}
div[data-testid="stChatMessageContent"] pre {
    background: #12121a;
    border: 1px solid #27273a;
    border-radius: 12px;
    padding: 1rem;
}

/* ---- chat input ---- */
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] input {
    background: #1a1a2e !important;
    border: 1px solid #27273a !important;
    border-radius: 16px !important;
    color: #f1f1f4 !important;
    padding: 14px 18px !important;
    font-size: 15px !important;
}
div[data-testid="stChatInput"] textarea:focus,
div[data-testid="stChatInput"] input:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15) !important;
}

/* ---- sidebar ---- */
section[data-testid="stSidebar"] {
    background: #12121a !important;
    border-right: 1px solid #27273a;
}
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button {
    background: #6366f1;
    color: #FFFFFF;
    border: none;
    border-radius: 12px;
    width: 100%;
    transition: all 0.25s ease;
}
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button:hover {
    background: #818cf8;
    color: #FFFFFF;
    transform: translateY(-1px);
}
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #f1f1f4;
    text-align: left;
    width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button:hover {
    background: #1a1a2e;
    border-color: #6366f1;
    color: #f1f1f4;
}

/* ---- quick actions ---- */
div[data-testid="stMain"] .stButton > button {
    background: #1a1a2e;
    border: 1px solid #27273a;
    color: #f1f1f4;
    padding: 12px 14px;
    border-radius: 12px;
    font-size: 14px;
    width: 100%;
    white-space: normal;
    line-height: 1.4;
    transition: all 0.25s ease;
}
div[data-testid="stMain"] .stButton > button:hover {
    background: #6366f1;
    border-color: #6366f1;
    color: #FFFFFF;
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(99, 102, 241, 0.35);
}

/* ---- file uploaders ---- */
div[data-testid="stFileUploader"] {
    background: #1a1a2e;
    border: 1px solid #27273a;
    border-radius: 12px;
    padding: 8px 12px;
}
div[data-testid="stFileUploader"] button {
    background: #12121a;
    color: #f1f1f4;
    border: 1px solid #27273a;
    border-radius: 8px;
}
div[data-testid="stFileUploader"] button:hover {
    border-color: #6366f1;
    color: #FFFFFF;
}

/* ---- files + stats ---- */
.file-card {
    background: #1a1a2e;
    border: 1px solid #27273a;
    border-radius: 10px;
    padding: 10px 14px;
    margin: 6px 0;
    font-size: 13px;
    color: #f1f1f4;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
div[data-testid="stDownloadButton"] > button {
    background: #1a1a2e;
    color: #f1f1f4;
    border: 1px solid #6366f1;
    border-radius: 10px;
    width: 100%;
}
div[data-testid="stDownloadButton"] > button:hover {
    background: #6366f1;
    color: #FFFFFF;
    border-color: #6366f1;
}
.stats-box {
    background: #1a1a2e;
    border-radius: 12px;
    padding: 16px;
    border: 1px solid #27273a;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
.thinking {
    animation: pulse 1.5s infinite;
    color: #8b8b9e;
}

/* ---- composer plus menu + attachment chip ---- */
/* ---- + button overlaid inside the input, bottom-left ----
   (st.chat_input is a closed widget, so the + sits over its
   bottom-left corner via positioning; text is padded clear of it) */
div[data-testid="stPopover"] {
    width: fit-content;
    margin-top: -52px;
    margin-left: 12px;
    position: relative;
    z-index: 5;
    pointer-events: none;
}
div[data-testid="stPopover"] > button,
.stPopover > button {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: none;
    background: transparent;
    color: #8b8b9e;
    font-size: 22px;
    line-height: 1;
    padding: 0;
    box-shadow: none;
    pointer-events: auto;
}
div[data-testid="stPopover"] > button:hover,
.stPopover > button:hover {
    background: rgba(99, 102, 241, 0.15);
    color: #FFFFFF;
    box-shadow: none;
}
div[data-testid="stPopover"] > button svg {
    display: none;
}
div[data-testid="stChatInput"] textarea {
    padding-left: 52px !important;
}
div[data-testid="stPopoverBody"] {
    background: #1a1a2e;
    border: 1px solid #27273a;
    border-radius: 14px;
    width: 240px !important;
    max-width: 240px !important;
    min-width: 0 !important;
    padding: 6px !important;
    box-shadow: none !important;
}
div[data-testid="stPopoverBody"] div[data-testid="stBaseButton-secondary"] > button,
div[data-testid="stPopoverBody"] .stButton > button {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #f1f1f4;
    text-align: left;
    width: 100%;
    padding: 8px 10px;
    font-size: 14px;
    box-shadow: none;
    transform: none;
    white-space: normal;
    line-height: 1.4;
}
div[data-testid="stPopoverBody"] div[data-testid="stBaseButton-secondary"] > button:hover,
div[data-testid="stPopoverBody"] .stButton > button:hover {
    background: #27273a;
    border: none;
    color: #FFFFFF;
    box-shadow: none;
    transform: none;
}
div[data-testid="stPopoverBody"] div[data-testid="stBaseButton-secondary"] > button:focus,
div[data-testid="stPopoverBody"] .stButton > button:focus,
div[data-testid="stPopoverBody"] div[data-testid="stBaseButton-secondary"] > button:active,
div[data-testid="stPopoverBody"] .stButton > button:active,
div[data-testid="stPopoverBody"] div[data-testid="stBaseButton-secondary"] > button:focus-visible,
div[data-testid="stPopoverBody"] .stButton > button:focus-visible {
    background: transparent;
    border: none;
    color: #f1f1f4;
    outline: none;
    box-shadow: none;
    transform: none;
}
div[data-testid="stCameraInput"] {
    border: 1px solid #27273a;
    border-radius: 12px;
    padding: 8px;
}
.attach-chip {
    display: inline-block;
    background: #1a1a2e;
    border: 1px solid #6366f1;
    color: #f1f1f4;
    font-size: 13px;
    border-radius: 999px;
    padding: 6px 14px;
    margin-bottom: 8px;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
"""

st.markdown("<style>" + THEME_CSS + "</style>", unsafe_allow_html=True)


# ============== HELPERS ==============
def build_chat_history(messages: List[Dict[str, str]], limit: int = 10) -> List[Any]:
    """Convert UI messages to LangChain history (last N turns).

    Args:
        messages: Session message dicts with 'role' and 'content'.
        limit: Max messages to include.

    Returns:
        List of HumanMessage / AIMessage objects.
    """
    history: List[Any] = []
    for msg in messages[-limit:]:
        if msg["role"] == "user":
            history.append(HumanMessage(content=msg["content"]))
        else:
            history.append(AIMessage(content=msg["content"]))
    return history


def run_agent(user_input: str) -> str:
    """Answer via the tool loop, cascading tiers on runtime errors.

    Args:
        user_input: The user's prompt text.

    Returns:
        Assistant output text.
    """
    result: Dict[str, Any] = answer_with_fallback(
        user_input,
        build_chat_history(st.session_state.messages),
        first=st.session_state.get("active_tier"),
        memory_notes=st.session_state.get("memory_notes", ""),
    )
    st.session_state.active_tier = str(result["active_tier"])
    return str(result["output"])


def persist() -> None:
    """Save chats + open conversation to disk. Never breaks chat on failure."""
    try:
        save_store(
            st.session_state.get("chats", []),
            st.session_state.get("messages", []),
        )
    except Exception:
        pass


def _stage_upload(uploaded: Any, kind: str, src: str) -> None:
    """Save an uploader/camera value as the pending attachment (once per file).

    Args:
        uploaded: The UploadedFile value, or None.
        kind: Attachment kind: "pdf", "csv", or "image".
        src: Where it came from: "doc", "img", or "camera".
    """
    if uploaded is None:
        return
    mark: List[Any] = [src, getattr(uploaded, "name", ""), getattr(uploaded, "size", 0)]
    pending = st.session_state.get("pending_attach")
    if isinstance(pending, dict) and pending.get("mark") == mark:
        return
    if src == "camera":
        fname: str = f"camera_{uuid.uuid4().hex[:8]}.png"
    else:
        fname = f"uploaded_{getattr(uploaded, 'name', 'file') or 'file'}"
    with open(fname, "wb") as f:
        f.write(uploaded.getbuffer())
    st.session_state.pending_attach = {
        "kind": kind,
        "name": fname,
        "path": fname,
        "mark": mark,
    }
    st.rerun()


def render_assistant_response(
    user_text: str,
    extra_context: str = "",
    images: Optional[List[str]] = None,
) -> None:
    """Append user text (plus attachments) and render the assistant reply.

    Args:
        user_text: The user's prompt text.
        extra_context: Additional context (e.g. native file attachments)
            appended to what the agent sees, but not shown in chat.
        images: Local image paths to display in the user message.
    """
    attach = st.session_state.pop("pending_attach", None)
    force_search: bool = bool(st.session_state.get("force_search", False))
    st.session_state.force_search = False

    send_text: str = user_text + extra_context
    shown_images: List[str] = list(images or [])
    image_path: Any = None
    if isinstance(attach, dict):
        kind: str = str(attach.get("kind", ""))
        if kind == "pdf":
            send_text += (
                f"\n\n[Attached PDF: {attach.get('path', '')}. "
                "Use the read_pdf tool on this path if the request needs it.]"
            )
        elif kind == "csv":
            send_text += (
                f"\n\n[Attached CSV: {attach.get('path', '')}. "
                "Use the analyze_csv tool on this path if the request needs it.]"
            )
        else:
            image_path = attach.get("path")
            send_text += (
                f"\n\n[Attached image: {attach.get('name', 'image')}. "
                "You cannot view images; if asked about its contents, say so "
                "briefly and continue helping from the text.]"
            )
    if image_path:
        shown_images.insert(0, str(image_path))
    if force_search:
        send_text = (
            "Use web_search to find current information before answering.\n\n"
            + send_text
        )

    user_msg: Dict[str, Any] = {"role": "user", "content": user_text}
    if shown_images:
        user_msg["images"] = shown_images
    st.session_state.messages.append(user_msg)
    with st.chat_message("user"):
        for img_path in shown_images:
            if os.path.exists(img_path):
                st.image(img_path, width=280)
        st.markdown(user_text)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                output: str = run_agent(send_text)
                st.markdown(output)
                st.session_state.messages.append({"role": "assistant", "content": output})
                persist()

                for pptx in sorted(glob.glob("pptx_*.pptx")):
                    with open(pptx, "rb") as f:
                        st.download_button(
                            f"Download {pptx}",
                            f,
                            file_name=pptx,
                            key=f"dl-pptx-{pptx}-{len(st.session_state.messages)}",
                        )
                for docx in sorted(glob.glob("docx_*.docx")):
                    with open(docx, "rb") as f:
                        st.download_button(
                            f"Download {docx}",
                            f,
                            file_name=docx,
                            key=f"dl-docx-{docx}-{len(st.session_state.messages)}",
                        )

            except Exception as e:
                st.error(f"Error: {e}")


def archive_current_chat() -> None:
    """Stash current messages into sidebar history (keeps max 20)."""
    msgs: List[Dict[str, str]] = [dict(m) for m in st.session_state.messages]
    if not msgs:
        return
    title: str = next((m["content"] for m in msgs if m["role"] == "user"), "Untitled")
    st.session_state.chats.insert(0, {"title": title.strip()[:38], "messages": msgs})
    del st.session_state.chats[20:]


def tier_status(tier_name: str) -> tuple:
    """Map a tier name to (badge class, marker) for the status badge."""
    if tier_name == "Muse Spark 1.3":
        return ("online", "●")
    if tier_name.startswith("Gemini") or tier_name.startswith("Ling"):
        return ("fallback", "◐")
    return ("offline", "○")


# ============== SESSION STATE ==============
if "chats" not in st.session_state or "messages" not in st.session_state:
    stored = load_store()
    st.session_state.chats = stored["chats"]
    st.session_state.messages = stored["current"]

if "memory_notes" not in st.session_state:
    st.session_state.memory_notes = load_memory_notes()

if "pending_attach" not in st.session_state:
    st.session_state.pending_attach = None

if "force_search" not in st.session_state:
    st.session_state.force_search = False

if "active_tier" not in st.session_state:
    with st.spinner("Initializing..."):
        try:
            st.session_state.active_tier = probe_live_tier(timeout=20.0)
        except RuntimeError:
            from config import TIER_GETTERS

            configured: List[str] = [n for n, g in TIER_GETTERS if g() is not None]
            if not configured:
                st.error("No LLM available. Add OPENCODE_API_KEY or GEMINI_API_KEY to .env")
                st.info(
                    "Add at least one key to `.env` (OPENCODE_API_KEY or GEMINI_API_KEY), "
                    "or set them in Streamlit Cloud Secrets, then rerun the app."
                )
                st.stop()
            st.session_state.active_tier = configured[0]


# ============== SIDEBAR ==============
with st.sidebar:
    st.markdown(
        '<div style="text-align: center; padding: 24px 0 16px;">'
        '<h1 class="brand-title">Poka</h1>'
        '<p style="color: #8b8b9e; font-size: 13px; margin-top: 6px;">Multi-purpose AI Assistant</p>'
        "</div>",
        unsafe_allow_html=True,
    )

    model_name: str = str(st.session_state.active_tier)
    status_class, status_icon = tier_status(model_name)
    st.markdown(
        '<div style="text-align: center; margin-bottom: 24px;">'
        f'<span class="status-badge status-{status_class}">{status_icon} {model_name}</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    if st.button("+ New chat", type="primary", key="new-chat"):
        archive_current_chat()
        st.session_state.messages = []
        persist()
        st.rerun()

    if st.session_state.chats:
        st.markdown('<p class="section-label">Chats</p>', unsafe_allow_html=True)
        for i, chat in enumerate(list(st.session_state.chats)):
            chat_title: str = str(chat.get("title", "Untitled"))[:34] or "Untitled"
            if st.button(chat_title, key=f"hist-{i}"):
                selected: Dict[str, Any] = st.session_state.chats.pop(i)
                archive_current_chat()
                st.session_state.messages = selected["messages"]
                persist()
                st.rerun()

    with st.expander("Memory"):
        st.caption("Things Poka should always remember.")
        notes_in = st.text_area(
            "Memory notes",
            value=st.session_state.get("memory_notes", ""),
            height=120,
            label_visibility="collapsed",
            key="memory-box",
        )
        if st.button("Save memory", key="save-memory"):
            save_memory_notes(notes_in)
            st.session_state.memory_notes = notes_in
            st.toast("Memory saved")

    with st.expander("Files & stats", expanded=False):
        st.markdown('<p class="section-label">Generated Files</p>', unsafe_allow_html=True)
        all_files: List[str] = sorted(glob.glob("pptx_*.pptx") + glob.glob("docx_*.docx"))
        if all_files:
            for fname in all_files[-5:]:
                st.markdown(f'<div class="file-card">{fname}</div>', unsafe_allow_html=True)
                with open(fname, "rb") as f:
                    st.download_button("Get file", f, file_name=fname, key=f"side-dl-{fname}")
        else:
            st.markdown(
                '<p style="color: #555; font-size: 12px; text-align: center;">No files yet</p>',
                unsafe_allow_html=True,
            )

        st.markdown('<p class="section-label">Stats</p>', unsafe_allow_html=True)
        st.markdown(
            '<div class="stats-box">'
            '<div style="display: flex; justify-content: space-between; margin-bottom: 10px;">'
            '<span style="color: #8b8b9e; font-size: 13px;">Messages</span>'
            f'<span style="color: #f1f1f4; font-weight: 600;">{len(st.session_state.messages)}</span>'
            "</div>"
            '<div style="display: flex; justify-content: space-between; margin-bottom: 10px;">'
            '<span style="color: #8b8b9e; font-size: 13px;">Files</span>'
            f'<span style="color: #f1f1f4; font-weight: 600;">{len(all_files)}</span>'
            "</div>"
            '<div style="display: flex; justify-content: space-between;">'
            '<span style="color: #8b8b9e; font-size: 13px;">Active</span>'
            f'<span style="color: #6366f1; font-weight: 600; font-size: 12px;">{model_name}</span>'
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )


# ============== MAIN ==============
if not st.session_state.messages:
    st.markdown(
        '<div class="hero"><h1>What can I help you with?</h1>'
        "<p>Presentations, documents, research, data analysis — just ask.</p></div>",
        unsafe_allow_html=True,
    )

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        msg_images: List[str] = []
        if isinstance(msg.get("images"), list):
            msg_images = [str(p) for p in msg["images"]]
        elif msg.get("image"):
            msg_images = [str(msg["image"])]
        for img_path in msg_images:
            if os.path.exists(img_path):
                st.image(img_path, width=280)
        st.markdown(msg["content"])

pending = st.session_state.get("pending_attach")
if isinstance(pending, dict):
    chip_text, chip_x = st.columns([5, 1])
    chip_text.markdown(
        f'<div class="attach-chip">Attached: {html.escape(str(pending.get("name", "file")))}</div>',
        unsafe_allow_html=True,
    )
    if chip_x.button("x", key="rm-attach"):
        st.session_state.pending_attach = None
        st.rerun()
elif st.session_state.get("force_search"):
    st.caption("Web search will be used for the next message.")

prompt = st.chat_input("Type your message...")

with st.popover("+"):
    if "attach_menu" not in st.session_state:
        st.session_state.attach_menu = None
    menu: Any = st.session_state.attach_menu
    if st.button("Add files or photos", key="m-files"):
        st.session_state.attach_menu = None if menu == "files" else "files"
        st.rerun()
    if st.session_state.attach_menu == "files":
        doc = st.file_uploader(
            "Add files or photos",
            type=["pdf", "csv", "png", "jpg", "jpeg"],
            label_visibility="collapsed",
        )
        if doc is not None:
            ext: str = str(doc.name).lower().rsplit(".", 1)[-1]
            if ext == "pdf":
                doc_kind: str = "pdf"
            elif ext == "csv":
                doc_kind = "csv"
            else:
                doc_kind = "image"
            _stage_upload(doc, doc_kind, "menu")
    if st.button("Take a screenshot", key="m-cam"):
        st.session_state.attach_menu = None if menu == "camera" else "camera"
        st.rerun()
    if st.session_state.attach_menu == "camera":
        shot = st.camera_input("Take a screenshot", label_visibility="collapsed")
        _stage_upload(shot, "image", "camera")
    search_on: bool = bool(st.session_state.get("force_search", False))
    if st.button(("✓ " if search_on else "") + "Web search", key="m-search"):
        st.session_state.force_search = not search_on
        st.rerun()

if prompt:
    render_assistant_response(prompt)

    st.markdown(
        f'<div style="text-align: center; padding: 24px; color: #555; font-size: 12px;">'
        f"<p>Poka v1.0 — Powered by {model_name}</p>"
        f"</div>",
        unsafe_allow_html=True,
    )
