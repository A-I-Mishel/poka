"""Poka visual theme (extracted from app.py; behavior unchanged)."""

import streamlit as st


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
    position: relative;
}

/* Copy button injected on assistant messages (hover to reveal) */
.poka-copy {
    position: absolute;
    top: 8px;
    right: 10px;
    background: #27273a;
    color: #f1f1f4;
    border: 1px solid #34344a;
    border-radius: 8px;
    font-size: 11px;
    padding: 3px 10px;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.15s ease;
    z-index: 3;
}
div[data-testid="stChatMessage"]:hover .poka-copy {
    opacity: 1;
}
@media (hover: none) {
    .poka-copy {
        opacity: 1;
    }
}

/* Edit button row under each user message (keyed containers render
   st-key-msgrow-N classes, matched here by substring) */
div[class*="st-key-msgrow-"] {
    display: flex;
    justify-content: flex-end;
}
div[class*="st-key-msgrow-"] div[data-testid="stBaseButton-secondary"] > button,
div[class*="st-key-msgrow-"] .stButton > button {
    width: auto;
    background: transparent;
    border: 1px solid #27273a;
    color: #8b8b9e;
    font-size: 12px;
    border-radius: 999px;
    padding: 4px 16px;
    text-align: center;
}
div[class*="st-key-msgrow-"] div[data-testid="stBaseButton-secondary"] > button:hover,
div[class*="st-key-msgrow-"] .stButton > button:hover {
    color: #FFFFFF;
    border-color: #6366f1;
    background: transparent;
    transform: none;
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


/* Typing indicator (three bouncing dots) */
.typing-indicator {
    display: flex;
    gap: 6px;
    padding: 16px 20px;
    align-items: center;
}
.typing-indicator span {
    width: 8px;
    height: 8px;
    background: #6366f1;
    border-radius: 50%;
    animation: bounce 1.4s infinite ease-in-out both;
}
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce {
    0%, 80%, 100% { transform: scale(0); }
    40% { transform: scale(1); }
}
mark.search-hit {
    background: rgba(99, 102, 241, 0.45);
    color: inherit;
    border-radius: 3px;
    padding: 0 2px;
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


def apply_theme() -> None:
    """Inject the Poka theme into the page."""
    st.markdown("<style>" + THEME_CSS + "</style>", unsafe_allow_html=True)
