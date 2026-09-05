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
