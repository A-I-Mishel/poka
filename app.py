"""Streamlit UI for Poka -- indigo dark theme, no emojis."""

import glob
import html
import os
import uuid
from typing import Any, Dict, List

import streamlit as st
import streamlit.components.v1 as components
from langchain_core.messages import AIMessage, HumanMessage

from agent import answer_with_fallback, probe_live_tier
from store import load_memory_notes, load_store, save_memory_notes, save_store


st.set_page_config(
    page_title="Poka",
    page_icon="*",
    layout="centered",
)


# ============================================================
# THEME
# ============================================================

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

#MainMenu {
    visibility: hidden;
}

footer {
    visibility: hidden;
}

::-webkit-scrollbar {
    width: 6px;
}

::-webkit-scrollbar-track {
    background: #0a0a0f;
}

::-webkit-scrollbar-thumb {
    background: #27273a;
    border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
    background: #6366f1;
}


/* ============================================================
   BRAND + HERO
   ============================================================ */

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


/* ============================================================
   STATUS BADGE
   ============================================================ */

.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 500;
}

.status-online {
    background: rgba(16, 185, 129, 0.12);
    color: #10b981;
}

.status-fallback {
    background: rgba(245, 158, 11, 0.12);
    color: #f59e0b;
}

.status-offline {
    background: rgba(239, 68, 68, 0.12);
    color: #ef4444;
}


/* ============================================================
   CHAT BUBBLES
   ============================================================ */

@keyframes slideRight {
    from {
        opacity: 0;
        transform: translateX(25px);
    }

    to {
        opacity: 1;
        transform: translateX(0);
    }
}

@keyframes slideLeft {
    from {
        opacity: 0;
        transform: translateX(-25px);
    }

    to {
        opacity: 1;
        transform: translateX(0);
    }
}

div[data-testid="stChatMessage"] {
    background: transparent;
    border: none;
    padding: 0.4rem 0;
}

div[data-testid="stChatMessage"]:has(
    div[data-testid="stChatMessageAvatarUser"]
) div[data-testid="stChatMessageAvatarUser"] {
    display: none;
}

div[data-testid="stChatMessage"]:has(
    div[data-testid="stChatMessageAvatarUser"]
) div[data-testid="stChatMessageContent"] {
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

div[data-testid="stChatMessage"]:has(
    div[data-testid="stChatMessageAvatarAssistant"]
) div[data-testid="stChatMessageContent"] {
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


/* ============================================================
   SIDEBAR
   ============================================================ */

section[data-testid="stSidebar"] {
    background: #12121a !important;
    border-right: 1px solid #27273a;
}

section[data-testid="stSidebar"]
div[data-testid="stBaseButton-primary"] > button {
    background: #6366f1;
    color: #FFFFFF;
    border: none;
    border-radius: 12px;
    width: 100%;
    transition: all 0.25s ease;
}

section[data-testid="stSidebar"]
div[data-testid="stBaseButton-primary"] > button:hover {
    background: #818cf8;
    color: #FFFFFF;
    transform: translateY(-1px);
}

section[data-testid="stSidebar"]
div[data-testid="stBaseButton-secondary"] > button {
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

section[data-testid="stSidebar"]
div[data-testid="stBaseButton-secondary"] > button:hover {
    background: #1a1a2e;
    border-color: #6366f1;
    color: #f1f1f4;
}


/* ============================================================
   FILE UPLOADER
   ============================================================ */

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


/* ============================================================
   FILES + STATS
   ============================================================ */

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


/* ============================================================
   THINKING
   ============================================================ */

@keyframes pulse {
    0%, 100% {
        opacity: 1;
    }

    50% {
        opacity: 0.4;
    }
}

.thinking {
    animation: pulse 1.5s infinite;
    color: #8b8b9e;
}


/* ============================================================
   CUSTOM CHAT COMPOSER — V4
   ============================================================ */

.st-key-composer {
    position: fixed !important;
    left: 50% !important;
    transform: translateX(-50%) !important;

    bottom: 22px !important;

    width: min(800px, calc(100vw - 48px)) !important;

    background: #15151b !important;
    background-color: #15151b !important;

    border: 1px solid #30303a !important;
    border-radius: 22px !important;

    padding: 8px 10px !important;

    box-sizing: border-box !important;
    z-index: 9999 !important;

    box-shadow:
        0 14px 36px rgba(0, 0, 0, 0.30) !important;

    transition:
        border-color 0.18s ease,
        box-shadow 0.18s ease !important;
}

.st-key-composer:focus-within {
    border-color: #3a3a46 !important;
    box-shadow:
        0 14px 36px rgba(0, 0, 0, 0.32),
        0 0 0 3px rgba(99, 102, 241, 0.06) !important;
}

/* ============================================================
   STREAMLIT LAYOUT RESET INSIDE COMPOSER
   ============================================================ */

.st-key-composer [data-testid="stVerticalBlock"] {
    gap: 0 !important;
}

.st-key-composer [data-testid="stHorizontalBlock"] {
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;

    gap: 5px !important;
    align-items: center !important;
}

.st-key-composer [data-testid="column"] {
    min-width: 0 !important;
    padding: 0 !important;
    margin: 0 !important;

    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}

/* ============================================================
   TEXT INPUT — HARD RESET ALL STREAMLIT / BASEWEB SURFACES
   ============================================================ */

.st-key-composer [data-testid="stTextInput"] {
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
}

.st-key-composer [data-testid="stTextInput"] label {
    display: none !important;
}

/*
   Streamlit's text_input uses several nested BaseWeb elements.
   Reset the complete subtree so there is NO inner rounded box.
*/
.st-key-composer [data-testid="stTextInput"] div,
.st-key-composer [data-testid="stTextInput"] span,
.st-key-composer [data-testid="stTextInput"] input,
.st-key-composer [data-testid="stTextInput"] [data-baseweb],
.st-key-composer [data-testid="stTextInput"] [data-baseweb="input"],
.st-key-composer [data-testid="stTextInput"] [data-baseweb="base-input"] {
    background: transparent !important;
    background-color: transparent !important;
    background-image: none !important;

    border: 0 !important;
    border-width: 0 !important;
    border-style: none !important;
    border-color: transparent !important;
    border-radius: 0 !important;

    outline: none !important;

    box-shadow: none !important;
}

/* Keep the input readable and vertically centered. */
.st-key-composer [data-testid="stTextInput"] input {
    -webkit-appearance: none !important;
    appearance: none !important;

    width: 100% !important;

    color: #f1f1f4 !important;
    -webkit-text-fill-color: #f1f1f4 !important;

    font-family:
        'Inter',
        system-ui,
        -apple-system,
        'Segoe UI',
        sans-serif !important;

    font-size: 15px !important;
    font-weight: 400 !important;
    line-height: 1.4 !important;

    padding: 11px 8px !important;
    margin: 0 !important;

    min-height: 42px !important;
    height: 42px !important;

    caret-color: #9c9eff !important;
}

.st-key-composer [data-testid="stTextInput"] input::placeholder {
    color: #787884 !important;
    -webkit-text-fill-color: #787884 !important;
    opacity: 1 !important;
}

/* Remove any focus treatment generated by BaseWeb. */
.st-key-composer [data-testid="stTextInput"] *:focus,
.st-key-composer [data-testid="stTextInput"] *:focus-visible,
.st-key-composer [data-testid="stTextInput"] *:focus-within {
    background: transparent !important;
    background-color: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
    outline: none !important;
}

/* ============================================================
   BUTTON BASE
   ============================================================ */

.st-key-composer button {
    width: 40px !important;
    height: 40px !important;
    min-width: 40px !important;
    max-width: 40px !important;

    padding: 0 !important;
    margin: 0 !important;

    border-radius: 50% !important;

    display: flex !important;
    align-items: center !important;
    justify-content: center !important;

    font-family:
        'Inter',
        system-ui,
        -apple-system,
        'Segoe UI',
        sans-serif !important;

    font-size: 19px !important;
    font-weight: 400 !important;
    line-height: 1 !important;

    box-shadow: none !important;

    transition:
        background-color 0.16s ease,
        border-color 0.16s ease,
        color 0.16s ease,
        transform 0.16s ease,
        box-shadow 0.16s ease !important;
}

/* ============================================================
   PLUS BUTTON
   ============================================================ */

.st-key-composer [data-testid="column"]:first-child button {
    background: transparent !important;
    background-color: transparent !important;

    border: 1px solid transparent !important;

    color: #9a9aa5 !important;
}

.st-key-composer [data-testid="column"]:first-child button:hover {
    background: #23232c !important;
    background-color: #23232c !important;

    border-color: #30303b !important;

    color: #f1f1f4 !important;

    transform: scale(1.03) !important;
}

.st-key-composer [data-testid="column"]:first-child button:active {
    transform: scale(0.95) !important;
}

/* ============================================================
   SEND BUTTON
   ============================================================ */

.st-key-composer [data-testid="column"]:last-child button {
    background: #6366f1 !important;
    background-color: #6366f1 !important;

    border: 1px solid #6366f1 !important;

    color: #ffffff !important;

    font-size: 18px !important;
    font-weight: 500 !important;
}

.st-key-composer [data-testid="column"]:last-child button:hover {
    background: #7679f5 !important;
    background-color: #7679f5 !important;

    border-color: #7679f5 !important;

    color: #ffffff !important;

    transform: scale(1.04) !important;

    box-shadow:
        0 5px 16px rgba(99, 102, 241, 0.24) !important;
}

.st-key-composer [data-testid="column"]:last-child button:active {
    background: #595bd5 !important;
    background-color: #595bd5 !important;

    border-color: #595bd5 !important;

    transform: scale(0.95) !important;

    box-shadow: none !important;
}

/* ============================================================
   MOBILE
   ============================================================ */

@media (max-width: 700px) {

    .st-key-composer {
        width: calc(100vw - 20px) !important;
        bottom: 10px !important;

        padding: 7px 8px !important;
        border-radius: 18px !important;
    }

    .st-key-composer [data-testid="stHorizontalBlock"] {
        gap: 4px !important;
    }

    .st-key-composer button {
        width: 36px !important;
        height: 36px !important;
        min-width: 36px !important;
        max-width: 36px !important;
    }

    .st-key-composer [data-testid="stTextInput"] input {
        font-size: 14px !important;
        min-height: 38px !important;
        height: 38px !important;
        padding: 9px 6px !important;
    }
}

/* ============================================================
   ATTACHMENT MENU
   ============================================================ */

.st-key-attachment-menu {
    position: fixed !important;

    left: max(
        16px,
        calc(50% - 24rem)
    ) !important;

    bottom: 90px !important;

    width: 270px !important;

    background: #1a1a2e !important;

    border: 1px solid #27273a !important;

    border-radius: 14px !important;

    padding: 8px !important;

    z-index: 10000 !important;

    box-shadow:
        0 12px 40px rgba(0, 0, 0, 0.40) !important;
}


/* ============================================================
   ATTACHMENT MENU BUTTONS
   ============================================================ */

.st-key-attachment-menu button {
    width: 100% !important;

    min-height: 42px !important;

    border: none !important;

    border-radius: 9px !important;

    background: transparent !important;

    color: #f1f1f4 !important;

    text-align: left !important;

    padding: 10px 12px !important;

    font-size: 14px !important;

    box-shadow: none !important;
}

.st-key-attachment-menu button:hover {
    background: #27273a !important;
    color: #FFFFFF !important;
}


/* ============================================================
   CAMERA
   ============================================================ */

div[data-testid="stCameraInput"] {
    border: 1px solid #27273a;
    border-radius: 12px;
    padding: 8px;
}


/* ============================================================
   ATTACHMENT CHIP
   ============================================================ */

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


/* ============================================================
   PAGE BOTTOM SPACE
   ============================================================ */

section[data-testid="stMain"] .block-container {
    padding-bottom: 135px !important;
}


/* ============================================================
   MOBILE
   ============================================================ */

@media (max-width: 700px) {

    .st-key-composer {
        width: calc(100vw - 20px) !important;
        bottom: 10px !important;
        padding: 7px !important;
        border-radius: 14px !important;
    }

    .st-key-composer button {
        width: 34px !important;
        height: 34px !important;
        min-width: 34px !important;
        max-width: 34px !important;
    }

    .st-key-composer
    div[data-testid="stTextInput"] input {
        font-size: 14px !important;
    }

    .st-key-attachment-menu {
        left: 10px !important;
        bottom: 70px !important;
        width: calc(100vw - 20px) !important;
        max-width: 300px !important;
    }
}
"""


st.markdown(
    "<style>" + THEME_CSS + "</style>",
    unsafe_allow_html=True,
)


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


def run_agent(user_input: str) -> str:
    """Answer via the tool loop."""
    result: Dict[str, Any] = answer_with_fallback(
        user_input,
        build_chat_history(
            st.session_state.messages
        ),
        first=st.session_state.get("active_tier"),
        memory_notes=st.session_state.get(
            "memory_notes",
            "",
        ),
    )

    st.session_state.active_tier = str(
        result["active_tier"]
    )

    return str(result["output"])


def persist() -> None:
    """Save chats + open conversation."""
    try:
        save_store(
            st.session_state.get("chats", []),
            st.session_state.get("messages", []),
        )
    except Exception:
        pass


def _stage_upload(
    uploaded: Any,
    kind: str,
    src: str,
) -> None:
    """Save an uploader/camera value as pending attachment."""
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

    if src == "camera":
        fname: str = (
            f"camera_{uuid.uuid4().hex[:8]}.png"
        )
    else:
        fname: str = (
            f"uploaded_"
            f"{getattr(uploaded, 'name', 'file') or 'file'}"
        )

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
) -> None:
    """Append user text and render assistant reply."""

    attach = st.session_state.pop(
        "pending_attach",
        None,
    )

    force_search: bool = bool(
        st.session_state.get(
            "force_search",
            False,
        )
    )

    st.session_state.force_search = False

    send_text: str = user_text

    image_path: Any = None

    if isinstance(attach, dict):

        kind: str = str(
            attach.get("kind", "")
        )

        if kind == "pdf":

            send_text += (
                f"\n\n[Attached PDF: "
                f"{attach.get('path', '')}. "
                "Use the read_pdf tool on this path "
                "if the request needs it.]"
            )

        elif kind == "csv":

            send_text += (
                f"\n\n[Attached CSV: "
                f"{attach.get('path', '')}. "
                "Use the analyze_csv tool on this path "
                "if the request needs it.]"
            )

        else:

            image_path = attach.get(
                "path"
            )

            send_text += (
                f"\n\n[Attached image: "
                f"{attach.get('name', 'image')}. "
                "You cannot view images; if asked "
                "about its contents, say so briefly "
                "and continue helping from the text.]"
            )

    if force_search:

        send_text = (
            "Use web_search to find current "
            "information before answering.\n\n"
            + send_text
        )

    user_msg: Dict[str, Any] = {
        "role": "user",
        "content": user_text,
    }

    if image_path:
        user_msg["image"] = str(image_path)

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

        with st.spinner("Thinking..."):

            try:

                output: str = run_agent(
                    send_text
                )

                st.markdown(output)

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": output,
                    }
                )

                persist()

                for pptx in sorted(
                    glob.glob("pptx_*.pptx")
                ):

                    with open(
                        pptx,
                        "rb",
                    ) as f:

                        st.download_button(
                            f"Download {pptx}",
                            f,
                            file_name=pptx,
                            key=(
                                f"dl-pptx-"
                                f"{pptx}-"
                                f"{len(st.session_state.messages)}"
                            ),
                        )

                for docx in sorted(
                    glob.glob("docx_*.docx")
                ):

                    with open(
                        docx,
                        "rb",
                    ) as f:

                        st.download_button(
                            f"Download {docx}",
                            f,
                            file_name=docx,
                            key=(
                                f"dl-docx-"
                                f"{docx}-"
                                f"{len(st.session_state.messages)}"
                            ),
                        )

            except Exception as e:

                st.error(
                    f"Error: {e}"
                )


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
        or tier_name.startswith("Ling")
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

    stored = load_store()

    st.session_state.chats = (
        stored["chats"]
    )

    st.session_state.messages = (
        stored["current"]
    )


if "memory_notes" not in st.session_state:
    st.session_state.memory_notes = (
        load_memory_notes()
    )


if "pending_attach" not in st.session_state:
    st.session_state.pending_attach = None


if "force_search" not in st.session_state:
    st.session_state.force_search = False


if "attach_menu" not in st.session_state:
    st.session_state.attach_menu = None


if "composer_key" not in st.session_state:
    st.session_state.composer_key = 0


if "show_attach_menu" not in st.session_state:
    st.session_state.show_attach_menu = False


if "active_tier" not in st.session_state:

    with st.spinner("Initializing..."):

        try:

            st.session_state.active_tier = (
                probe_live_tier(timeout=20.0)
            )

        except RuntimeError:

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

    if st.button(
        "+ New chat",
        type="primary",
        key="new-chat",
    ):

        archive_current_chat()

        st.session_state.messages = []

        persist()

        st.rerun()


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

            save_memory_notes(notes_in)

            st.session_state.memory_notes = (
                notes_in
            )

            st.toast("Memory saved")


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

        all_files: List[str] = sorted(
            glob.glob("pptx_*.pptx")
            + glob.glob("docx_*.docx")
        )

        if all_files:

            for fname in all_files[-5:]:

                st.markdown(
                    f'<div class="file-card">'
                    f'{fname}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                with open(
                    fname,
                    "rb",
                ) as f:

                    st.download_button(
                        "Get file",
                        f,
                        file_name=fname,
                        key=f"side-dl-{fname}",
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
            f'{len(all_files)}'
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
for msg in st.session_state.messages:

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
            msg["content"]
        )


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
components.html(
    """
<script>
(function () {
    const doc = window.parent.document;
    const scope = doc.querySelector(".st-key-composer");
    if (!scope || scope.dataset.enterBound) return;
    scope.dataset.enterBound = "1";
    const input = scope.querySelector('div[data-testid="stTextInput"] input');
    if (!input) return;
    input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            const btns = scope.querySelectorAll("button");
            const send = btns[btns.length - 1];
            if (send) send.click();
        }
    });
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
            "Take a screenshot",
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
                "Take a screenshot",
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
