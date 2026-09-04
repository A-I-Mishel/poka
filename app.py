"""Streamlit UI for Poka."""

import glob
import os
from typing import Any, Dict, List

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

from agent import answer_with_fallback, probe_live_tier

st.set_page_config(page_title="Poka", page_icon="\u2733", layout="centered")
st.title("\u2733 Poka")
st.caption("Muse Spark 1.3 \u2192 Gemini 3.6 \u2192 Gemini 3.5")


def apply_claude_theme() -> None:
    """Inject a Claude-inspired warm theme (cream paper, terracotta accent, serif replies)."""
    st.markdown(
        """
<style>
.stApp {
    background-color: #F7F5F0;
    color: #23211D;
}
section[data-testid="stMain"] .block-container,
div[data-testid="stMainBlockContainer"] {
    max-width: 48rem;
}
header[data-testid="stHeader"] {
    background: rgba(247, 245, 240, 0.0);
}
header[data-testid="stHeader"] button {
    color: #6B675E;
}
footer {
    visibility: hidden;
}
.stApp h1 {
    font-family: Georgia, 'Times New Roman', serif;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: #23211D;
}
.stApp [data-testid="stCaptionContainer"] p {
    color: #8A8478;
}
/* ---- chat messages ---- */
div[data-testid="stChatMessage"] {
    background: transparent;
    border: none;
    padding: 0.6rem 0;
}
/* user bubble, right aligned */
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageAvatarUser"] {
    display: none;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] {
    background-color: #ECE8DD;
    border-radius: 1.1rem;
    padding: 0.7rem 1.1rem;
    margin-left: auto;
    max-width: 82%;
    color: #23211D;
}
/* assistant: plain on paper, serif like Claude */
div[data-testid="stChatMessageAvatarAssistant"] {
    background-color: #C15F3C;
    border-radius: 50%;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 1.04rem;
    line-height: 1.72;
    color: #2A2721;
    max-width: 100%;
}
div[data-testid="stChatMessageContent"] a {
    color: #C15F3C;
}
/* ---- chat input: rounded pill ---- */
div[data-testid="stChatInput"] textarea {
    background-color: #FFFFFF;
    border: 1px solid #E0DACB;
    border-radius: 1.4rem !important;
    box-shadow: 0 2px 10px rgba(60, 50, 35, 0.07);
    color: #23211D;
}
div[data-testid="stChatInput"] textarea:focus {
    border-color: #C15F3C;
    box-shadow: 0 0 0 1px #C15F3C;
}
/* ---- sidebar ---- */
section[data-testid="stSidebar"] {
    background-color: #F0EDE4;
}
section[data-testid="stSidebar"] .stButton > button {
    border: 1px solid #C15F3C;
    color: #C15F3C;
    border-radius: 999px;
    background-color: transparent;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background-color: #C15F3C;
    color: #FFFFFF;
}
/* ---- download buttons ---- */
div[data-testid="stDownloadButton"] > button {
    background-color: #C15F3C;
    color: #FFFFFF;
    border: none;
    border-radius: 999px;
}
div[data-testid="stDownloadButton"] > button:hover {
    background-color: #A94E2F;
    color: #FFFFFF;
}
/* success line showing active model */
div[data-testid="stSidebar"] div[data-testid="stNotificationContentSuccess"] {
    background-color: #E7EFE4;
}
</style>
        """,
        unsafe_allow_html=True,
    )


apply_claude_theme()


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

st.sidebar.success(f"Active model: {st.session_state.active_tier}")
st.sidebar.header("\U0001F4C1 Upload Files")
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

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("What do you need help with?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                output: str = run_agent(prompt)
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

# Show existing generated files in sidebar for easy access.
with st.sidebar.expander("Generated files"):
    gen_files: List[str] = sorted(glob.glob("pptx_*.pptx") + glob.glob("docx_*.docx"))
    if not gen_files:
        st.write("No files generated yet.")
    else:
        for fname in gen_files:
            st.write(f"\u2022 {fname} ({os.path.getsize(fname)} bytes)")
