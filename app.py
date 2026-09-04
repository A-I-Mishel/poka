"""Streamlit UI for Poka."""

import glob
import os
from datetime import datetime
from typing import Any, Dict, List

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

from agent import answer_with_fallback, probe_live_tier

st.set_page_config(page_title="Poka", page_icon="\u2733", layout="centered")


THEMES: Dict[str, Dict[str, str]] = {
    "Light": {
        "paper": "#F7F5F0",
        "sidebar": "#F0EDE4",
        "ink": "#23211D",
        "assistant-ink": "#2A2721",
        "muted": "#8A8478",
        "bubble": "#ECE8DD",
        "input-bg": "#FFFFFF",
        "input-border": "#E0DACB",
        "accent": "#C15F3C",
        "accent-hover": "#A94E2F",
        "code-bg": "#EFEAE0",
        "shadow": "0 2px 10px rgba(60, 50, 35, 0.07)",
        "success-bg": "#E7EFE4",
    },
    "Dark": {
        "paper": "#201D18",
        "sidebar": "#191611",
        "ink": "#ECE7DB",
        "assistant-ink": "#E9E3D6",
        "muted": "#A39C8D",
        "bubble": "#38322A",
        "input-bg": "#292520",
        "input-border": "#4A4237",
        "accent": "#D97757",
        "accent-hover": "#E89370",
        "code-bg": "#2E2A23",
        "shadow": "0 2px 12px rgba(0, 0, 0, 0.35)",
        "success-bg": "#2A3A2C",
    },
}

_BASE_CSS: str = """
.stApp {
    background-color: var(--paper);
    color: var(--ink);
}
section[data-testid="stMain"] .block-container,
div[data-testid="stMainBlockContainer"] {
    max-width: 48rem;
}
header[data-testid="stHeader"] {
    background: rgba(0, 0, 0, 0.0);
}
header[data-testid="stHeader"] button {
    color: var(--muted);
}
footer {
    visibility: hidden;
}
::-webkit-scrollbar {
    width: 10px;
}
::-webkit-scrollbar-thumb {
    background: var(--input-border);
    border-radius: 8px;
}
.stApp h1 {
    font-family: Georgia, 'Times New Roman', serif;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--ink);
}
.stApp [data-testid="stCaptionContainer"] p {
    color: var(--muted);
}
/* ---- welcome hero ---- */
.poka-hero {
    text-align: center;
    margin: 9vh 0 1.6rem;
}
.poka-star {
    color: var(--accent);
    font-size: 2.4rem;
    line-height: 1;
    margin-bottom: 0.6rem;
}
.poka-hero h2 {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: clamp(1.7rem, 4.5vw, 2.5rem);
    font-weight: 600;
    color: var(--ink);
    margin-bottom: 0.4rem;
}
.poka-hero p {
    color: var(--muted);
    font-size: 1rem;
}
div[data-testid="stMain"] .stButton > button {
    width: 100%;
    text-align: left;
    background-color: var(--input-bg);
    color: var(--ink);
    border: 1px solid var(--input-border);
    border-radius: 1rem;
    padding: 0.8rem 1rem;
    box-shadow: var(--shadow);
    white-space: normal;
    line-height: 1.4;
}
div[data-testid="stMain"] .stButton > button:hover {
    border-color: var(--accent);
    color: var(--accent);
}
/* ---- chat messages ---- */
@keyframes pokaFade {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: none; }
}
div[data-testid="stChatMessage"] {
    background: transparent;
    border: none;
    padding: 0.6rem 0;
    animation: pokaFade 0.25s ease;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageAvatarUser"] {
    display: none;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] {
    background-color: var(--bubble);
    border-radius: 1.1rem;
    padding: 0.7rem 1.1rem;
    margin-left: auto;
    max-width: 82%;
    color: var(--ink);
}
div[data-testid="stChatMessageAvatarAssistant"] {
    background-color: var(--accent);
    border-radius: 50%;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 1.04rem;
    line-height: 1.72;
    color: var(--assistant-ink);
    max-width: 100%;
}
div[data-testid="stChatMessageContent"] a {
    color: var(--accent);
}
div[data-testid="stChatMessageContent"] code {
    background-color: var(--code-bg);
    border-radius: 0.35rem;
    padding: 0.1rem 0.35rem;
}
div[data-testid="stChatMessageContent"] pre {
    background-color: var(--code-bg);
    border-radius: 0.8rem;
    padding: 1rem;
}
/* ---- chat input: rounded pill ---- */
div[data-testid="stChatInput"] textarea {
    background-color: var(--input-bg);
    border: 1px solid var(--input-border);
    border-radius: 1.4rem !important;
    box-shadow: var(--shadow);
    color: var(--ink);
}
div[data-testid="stChatInput"] textarea:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
}
/* ---- sidebar nav (Claude-style) ---- */
section[data-testid="stSidebar"] {
    background-color: var(--sidebar);
}
.poka-brand {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 1.6rem;
    font-weight: 600;
    color: var(--ink);
    padding: 0.4rem 0 0.8rem;
}
.poka-brand span {
    color: var(--accent);
}
.poka-label {
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 1.1rem 0 0.4rem;
}
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button,
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background-color: var(--accent);
    color: #FFFFFF;
    border: none;
    border-radius: 999px;
    width: 100%;
}
section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] > button:hover,
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
    background-color: var(--accent-hover);
    color: #FFFFFF;
}
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button {
    background-color: transparent;
    border: none;
    border-radius: 0.6rem;
    color: var(--ink);
    text-align: left;
    width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] > button:hover {
    background-color: var(--bubble);
    color: var(--ink);
    border: none;
}
/* ---- download buttons ---- */
div[data-testid="stDownloadButton"] > button {
    background-color: var(--accent);
    color: #FFFFFF;
    border: none;
    border-radius: 999px;
}
div[data-testid="stDownloadButton"] > button:hover {
    background-color: var(--accent-hover);
    color: #FFFFFF;
}
div[data-testid="stSidebar"] div[data-testid="stNotificationContentSuccess"] {
    background-color: var(--success-bg);
}
"""


def apply_theme(mode: str) -> None:
    """Inject the warm theme for the given mode (Light/Dark).

    Args:
        mode: Theme name matching a key in THEMES.
    """
    palette: Dict[str, str] = THEMES.get(mode, THEMES["Light"])
    vars_block: str = "\n".join(f"    --{k}: {v};" for k, v in palette.items())
    st.markdown(
        "<style>\n.stApp {\n" + vars_block + "\n}\n" + _BASE_CSS + "\n</style>",
        unsafe_allow_html=True,
    )


if "theme" not in st.session_state:
    st.session_state.theme = "Dark"

apply_theme(st.session_state.theme)


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


def archive_current_chat() -> None:
    """Stash current messages into sidebar history (keeps max 20)."""
    msgs: List[Dict[str, str]] = [dict(m) for m in st.session_state.messages]
    if not msgs:
        return
    title: str = next((m["content"] for m in msgs if m["role"] == "user"), "Untitled")
    st.session_state.chats.insert(0, {"title": title.strip()[:38], "messages": msgs})
    del st.session_state.chats[20:]


def greeting_for_now() -> str:
    """Time-aware hero greeting, Claude-style."""
    hour: int = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning."
    if 12 <= hour < 17:
        return "Good afternoon."
    if 17 <= hour < 22:
        return "Good evening."
    return "Burning the midnight oil."


if "chats" not in st.session_state:
    st.session_state.chats = []

if "messages" not in st.session_state:
    st.session_state.messages = []

if "active_tier" not in st.session_state:
    with st.spinner("Connecting to fastest available model..."):
        try:
            st.session_state.active_tier = probe_live_tier(timeout=20.0)
        except RuntimeError:
            from config import TIER_GETTERS

            configured: List[str] = [n for n, g in TIER_GETTERS if g() is not None]
            if not configured:
                st.error("\u274C No LLM available. Add OPENCODE_API_KEY or GEMINI_API_KEY to .env")
                st.info(
                    "Add at least one key to `.env` (OPENCODE_API_KEY or GEMINI_API_KEY), "
                    "or set them in Streamlit Cloud Secrets, then rerun the app."
                )
                st.stop()
            st.session_state.active_tier = configured[0]

st.sidebar.markdown('<div class="poka-brand"><span>\u2733</span> Poka</div>', unsafe_allow_html=True)

if st.sidebar.button("\uff0b New chat", type="primary", key="new-chat"):
    archive_current_chat()
    st.session_state.messages = []
    st.rerun()

if st.session_state.chats:
    st.sidebar.markdown('<div class="poka-label">Chats</div>', unsafe_allow_html=True)
    for i, chat in enumerate(list(st.session_state.chats)):
        chat_title: str = str(chat.get("title", "Untitled"))[:34] or "Untitled"
        if st.sidebar.button(chat_title, key=f"hist-{i}"):
            selected: Dict[str, Any] = st.session_state.chats.pop(i)
            archive_current_chat()
            st.session_state.messages = selected["messages"]
            st.rerun()

st.sidebar.markdown('<div class="poka-label">Files</div>', unsafe_allow_html=True)
uploaded_pdf = st.sidebar.file_uploader("Upload PDF", type="pdf")
uploaded_csv = st.sidebar.file_uploader("Upload CSV", type="csv")

if uploaded_pdf:
    pdf_path: str = f"uploaded_{uploaded_pdf.name}"
    with open(pdf_path, "wb") as f:
        f.write(uploaded_pdf.getbuffer())
    if st.sidebar.button("Summarize PDF"):
        with st.spinner("Reading PDF..."):
            try:
                answer: str = run_agent(f"Read and summarize the PDF at {pdf_path}")
                st.session_state.messages.append(
                    {"role": "user", "content": f"Summarize PDF: {uploaded_pdf.name}"}
                )
                st.session_state.messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                st.error(f"Error: {e}")

if uploaded_csv:
    csv_path: str = f"uploaded_{uploaded_csv.name}"
    with open(csv_path, "wb") as f:
        f.write(uploaded_csv.getbuffer())
    if st.sidebar.button("Analyze CSV"):
        with st.spinner("Analyzing data..."):
            try:
                answer = run_agent(f"Analyze the CSV at {csv_path}")
                st.session_state.messages.append(
                    {"role": "user", "content": f"Analyze CSV: {uploaded_csv.name}"}
                )
                st.session_state.messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                st.error(f"Error: {e}")

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
                            f"\U0001F4E5 Download {pptx}",
                            f,
                            file_name=pptx,
                            key=f"dl-pptx-{pptx}-{len(st.session_state.messages)}",
                        )
                for docx in sorted(glob.glob("docx_*.docx")):
                    with open(docx, "rb") as f:
                        st.download_button(
                            f"\U0001F4E5 Download {docx}",
                            f,
                            file_name=docx,
                            key=f"dl-docx-{docx}-{len(st.session_state.messages)}",
                        )

            except Exception as e:
                st.error(f"Error: {e}")


SUGGESTIONS: List[tuple] = [
    ("\U0001F4DD Paragraph on the cow", "Write a paragraph on the cow"),
    ("\U0001F680 Space presentation", "Make a presentation on space exploration with 4 slides"),
    ("\U0001F50D Latest AI news", "Search the latest AI news and summarize it in bullets"),
]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if not st.session_state.messages:
    st.markdown(
        f'<div class="poka-hero"><div class="poka-star">\u2733</div><h2>{greeting_for_now()}</h2>'
        "<p>How can I help you today?</p></div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(3)
    for col, (label, full_prompt) in zip(cols, SUGGESTIONS):
        if col.button(label, key=f"sug-{label}"):
            render_assistant_response(full_prompt)

if prompt := st.chat_input("What do you need help with?"):
    render_assistant_response(prompt)

# Show existing generated files in sidebar for easy access.
with st.sidebar.expander("Generated files"):
    gen_files: List[str] = sorted(glob.glob("pptx_*.pptx") + glob.glob("docx_*.docx"))
    if not gen_files:
        st.write("No files generated yet.")
    else:
        for fname in gen_files:
            st.write(f"\u2022 {fname} ({os.path.getsize(fname)} bytes)")

st.sidebar.markdown('<div class="poka-label">Settings</div>', unsafe_allow_html=True)
st.sidebar.radio("Appearance", ["Light", "Dark"], horizontal=True, key="theme")
st.sidebar.caption(f"Active model: {st.session_state.active_tier}")
