"""Poka page composition: bootstrap, section order, send flow.

Application composition root. All behavior lives in focused modules:
- application.session: stores, agent calls, session bootstrap.
- ui.chat: history rendering, send/edit/retry flows.
- ui.sidebar: brand, status, chats, memory, files, stats.
- ui.uploads: attachment chip and plus-menu pickers.
- ui.composer: message input row.
- ui.components: formatting helpers and page script.
"""

import streamlit as st
import streamlit.components.v1 as components

from application.session import ensure_session_defaults
from services.auth import AuthRequired, authenticate, verify_access_token
from services.context import set_current_user_id
from services.memory import set_memory_dir
from services.storage import UserStore
from ui.chat import _retry_last, render_assistant_response, render_history
from ui.composer import render_composer
from ui.components import COMPOSER_SCRIPT
from ui.sidebar import render_sidebar
from ui.theme import apply_theme
from ui.uploads import render_attachment_chip, render_attachment_menu


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
        '<p style="color:var(--text-2);font-size:14px;">This app is private.</p>'
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


try:
    if _USER_ID:
        set_memory_dir(str(UserStore(_USER_ID).root))
except Exception:
    pass


# ============================================================
# THEME
# ============================================================

apply_theme()


# ============================================================
# SESSION DEFAULTS
# ============================================================

ensure_session_defaults()


# ============================================================
# SIDEBAR
# ============================================================

model_name = render_sidebar()


# ============================================================
# MAIN
# ============================================================

if not st.session_state.messages:

    st.markdown(
        '<div class="poka-home">'
        '<span class="poka-home-mark" aria-hidden="true">'
        '<svg viewBox="0 0 16 16" width="20" height="20">'
        '<path d="M8 0l1.8 5.6L15 7l-4 3.6L12.2 16 8 12.8 3.8 16 '
        '5 10.6 1 7l5.2-1.4z"/>'
        "</svg>"
        "</span>"
        "<h1>What can I help with?</h1>"
        "<p>"
        "Ask Poka to research, draft documents and presentations, "
        "analyze PDFs and data, or remember what matters to you."
        "</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    _suggestions = (
        (
            "Draft a presentation",
            "Turn a topic into slides",
            "Draft a short presentation about "
            "the future of renewable energy",
        ),
        (
            "Analyze a file",
            "PDFs, CSVs, and photos",
            "I will upload a file — help me "
            "analyze and summarize it",
        ),
        (
            "Research a topic",
            "Get answers with sources",
            "Research the latest developments in "
            "artificial intelligence and cite your sources",
        ),
        (
            "Explain a concept",
            "Break down something difficult",
            "Explain quantum computing in simple terms",
        ),
    )

    # Suggestion cards fill the existing composer input (same pattern
    # as Edit restore); sending still goes through the normal flow.
    with st.container(key="home"):
        _home_left, _home_right = st.columns(2)
        for _idx, (_title, _hint, _prompt) in enumerate(_suggestions):
            with _home_left if _idx % 2 == 0 else _home_right:
                with st.container(border=True):
                    if st.button(_title, key=f"suggest-{_idx}"):
                        st.session_state[
                            f"composer_input_"
                            f"{st.session_state.composer_key}"
                        ] = _prompt
                        st.rerun()
                    st.caption(_hint)


# Render conversation
render_history()


# ============================================================
# ATTACHMENT STATUS
# ============================================================

render_attachment_chip()


# ============================================================
# CUSTOM COMPOSER
# ============================================================

plus_clicked, send_clicked = render_composer()


# Enter key inside the composer input clicks Send (text_input alone
# only commits its value on Enter without submitting anything).
# Also keeps the chat pinned to the bottom while new messages arrive.
components.html(
    COMPOSER_SCRIPT,
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


render_attachment_menu()


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
