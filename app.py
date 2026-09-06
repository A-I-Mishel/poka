"""Poka page composition: bootstrap, section order, send flow.

Application composition root. All behavior lives in focused modules:
- application.session: stores, agent calls, session bootstrap.
- ui.chat: history rendering, send/edit/retry flows.
- ui.sidebar: brand, status, chats, memory, files, stats.
- ui.uploads: attachment chip and plus-menu pickers.
- ui.composer: message input row.
- ui.components: formatting helpers and page script.
"""

import html

import streamlit as st
import streamlit.components.v1 as components

from application.session import ensure_session_defaults
from services.auth import AuthRequired, authenticate, verify_access_token
from services.context import set_current_user_id
from services.memory import set_memory_dir
from services.storage import UserStore
from ui.chat import _retry_last, render_assistant_response, render_followups, render_history
from ui.composer import render_composer
from ui.components import COMPOSER_SCRIPT
from ui.sidebar import get_active_project, render_sidebar, render_workspace_view
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

# Subtle active-project context (re-resolved; Personal shows nothing).
_indicator_project = get_active_project()
if isinstance(_indicator_project, dict):
    _indicator_name = str(_indicator_project.get("name", "")).strip()[:60]
    if _indicator_name:
        _indicator_safe = html.escape(_indicator_name).replace("[", "\\[")
        st.caption(f"In project: {_indicator_safe}")

# Workspace destination (7F navigation-first): a selected destination
# renders here instead of home/chat. Composer, uploads, send, retry,
# and error flows below stay exactly as before.
try:
    _workspace_active = bool(st.session_state.get("sidebar_view"))
except Exception:
    _workspace_active = False

if _workspace_active:

    render_workspace_view()

if not _workspace_active and not st.session_state.messages:

    # Honest first-run guidance from existing state only: returning users
    # (archived chats) get a continue cue, new users get capabilities.
    _hero_sub = (
        "Welcome back — continue where you left off, "
        "or start something new below."
        if st.session_state.get("chats")
        else         "Research, draft documents, analyze files, "
        "and remember what matters to you."
    )

    st.markdown(
        '<div class="poka-home">'
        '<span class="poka-home-mark" aria-hidden="true">'
        '<svg viewBox="0 0 16 16" width="20" height="20">'
        '<path d="M8 0l1.8 5.6L15 7l-4 3.6L12.2 16 8 12.8 3.8 16 '
        '5 10.6 1 7l5.2-1.4z"/>'
        "</svg>"
        "</span>"
        '<p class="poka-eyebrow">Poka · AI workspace</p>'
        "<h1>What can I help with?</h1>"
        "<p>"
        + _hero_sub
        + "</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    _suggestions = (
        (
            "Create",
            "Slides, docs & plans",
            "Draft a short presentation about "
            "the future of renewable energy",
        ),
        (
            "Analyze files",
            "PDFs, CSVs & photos",
            "I will upload a file — help me "
            "analyze and summarize it",
        ),
        (
            "Research",
            "Cited answers",
            "Research the latest developments in "
            "artificial intelligence and cite your sources",
        ),
        (
            "Search the web",
            "Fresh answers + sources",
            "What happened in artificial intelligence "
            "this week? Cite your sources",
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


# Render conversation (skipped while a workspace destination is open;
# opening a workspace never destroys chat state).
if not _workspace_active:

    render_history()

    # Contextual follow-ups under the latest assistant reply (if any).
    render_followups()


# ============================================================
# ATTACHMENT STATUS
# ============================================================

render_attachment_chip()


# ============================================================
# MODE (compact Fast/Deep lives with the composer in 7F;
# same deep_mode state and keys, only placement moved)
# ============================================================

_mode_is_deep = bool(st.session_state.get("deep_mode", False))
_mode_a, _mode_b, _mode_rest = st.columns([1, 1, 6], gap="small")
with _mode_a:
    if st.button(
        "Fast",
        key="mode-fast",
        help="Fast mode",
        disabled=not _mode_is_deep,
    ):
        st.session_state.deep_mode = False
        st.rerun()
with _mode_b:
    if st.button(
        "Deep",
        key="mode-deep",
        help="Deep mode",
        disabled=_mode_is_deep,
    ):
        st.session_state.deep_mode = True
        st.rerun()


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
