"""Streamlit UI for Poka -- indigo dark theme, no emojis."""

import glob
import os
from datetime import datetime
from typing import Any, Dict, List

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

from agent import answer_with_fallback, probe_live_tier

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
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
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
    )
    st.session_state.active_tier = str(result["active_tier"])
    return str(result["output"])


def render_assistant_response(user_text: str) -> None:
    """Append user text and render the assistant reply with file downloads.

    Args:
        user_text: The user's prompt text.
    """
    st.session_state.messages.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                output: str = run_agent(user_text)
                st.markdown(output)
                st.session_state.messages.append({"role": "assistant", "content": output})

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
    if tier_name.startswith("Gemini"):
        return ("fallback", "◐")
    return ("offline", "○")


QUICK_ACTIONS: List[tuple] = [
    ("Space Presentation", "Create a 5-slide presentation on space exploration"),
    ("Professor Email", "Draft a professional email to my professor asking for a deadline extension"),
    ("Latest AI News", "Search for the latest AI news and summarize the top 3 stories"),
    ("Cow Paragraph", "Write a paragraph on the cow"),
]


# ============== SESSION STATE ==============
if "messages" not in st.session_state:
    st.session_state.messages = []

if "chats" not in st.session_state:
    st.session_state.chats = []

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
        st.rerun()

    if st.session_state.chats:
        st.markdown('<p class="section-label">Chats</p>', unsafe_allow_html=True)
        for i, chat in enumerate(list(st.session_state.chats)):
            chat_title: str = str(chat.get("title", "Untitled"))[:34] or "Untitled"
            if st.button(chat_title, key=f"hist-{i}"):
                selected: Dict[str, Any] = st.session_state.chats.pop(i)
                archive_current_chat()
                st.session_state.messages = selected["messages"]
                st.rerun()

    st.markdown('<p class="section-label">Upload Files</p>', unsafe_allow_html=True)

    uploaded_pdf = st.file_uploader("PDF Document", type="pdf", label_visibility="collapsed")
    uploaded_csv = st.file_uploader("CSV Data", type="csv", label_visibility="collapsed")

    if uploaded_pdf:
        pdf_path: str = f"uploaded_{uploaded_pdf.name}"
        with open(pdf_path, "wb") as f:
            f.write(uploaded_pdf.getbuffer())
        if st.button("Summarize PDF", key="sum-pdf"):
            with st.spinner("Reading..."):
                try:
                    answer: str = run_agent(f"Read and summarize the PDF at {pdf_path}")
                    st.session_state.messages.append(
                        {"role": "user", "content": f"Summarize: {uploaded_pdf.name}"}
                    )
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

    if uploaded_csv:
        csv_path: str = f"uploaded_{uploaded_csv.name}"
        with open(csv_path, "wb") as f:
            f.write(uploaded_csv.getbuffer())
        if st.button("Analyze CSV", key="ana-csv"):
            with st.spinner("Analyzing..."):
                try:
                    answer = run_agent(f"Analyze the CSV at {csv_path}")
                    st.session_state.messages.append(
                        {"role": "user", "content": f"Analyze: {uploaded_csv.name}"}
                    )
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

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
    quick_cols = st.columns(4)
    for col, (label, full_prompt) in zip(quick_cols, QUICK_ACTIONS):
        with col:
            if st.button(label, key=f"quick-{label}"):
                render_assistant_response(full_prompt)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Type your message..."):
    render_assistant_response(prompt)

st.markdown(
    '<div style="text-align: center; padding: 24px; color: #555; font-size: 12px;">'
    "<p>Poka v1.0 — Muse Spark 1.3 / Gemini 3.6 / Gemini 3.5</p>"
    "</div>",
    unsafe_allow_html=True,
)
