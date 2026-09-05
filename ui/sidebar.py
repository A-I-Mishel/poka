"""Sidebar: brand, model status, mode, chats, memory, files, stats.

Page section only: persistence and stores come from
application.session, memory facts from services.memory. Returns the
active model name for the page footer.
"""

import html

import streamlit as st

from application.session import (
    _file_store,
    _user_store,
    archive_current_chat,
    persist,
)
from services.memory import delete_memory_fact
from services.storage import StorageError
from services.timeutil import utcnow_stamp
from ui.components import _export_chat_to_markdown


def _active_model_name() -> str:
    """Read the existing active-model source of truth.

    Single reader for the sidebar: ``st.session_state.active_tier`` is
    initialized in ``application.session.ensure_session_defaults`` (from
    ``config.TIER_GETTERS``) and updated in ``run_agent`` from
    ``agent.answer_with_fallback``. No selection logic lives here.
    """
    return str(st.session_state.get("active_tier", "") or "")


def _model_is_live(model_name: str) -> bool:
    """Provider-agnostic liveness: only the known empty states are offline."""
    return model_name.strip().lower() not in (
        "",
        "no llm configured",
        "no user identity",
    )


def render_sidebar() -> str:
    """Render the full sidebar; return the active model name."""

    with st.sidebar:

        # ---- Brand (left aligned, quiet) ----
        st.markdown(
            '<div class="poka-brand">'
            '<span class="poka-mark" aria-hidden="true">'
            '<svg viewBox="0 0 16 16" width="16" height="16">'
            '<path d="M8 0l1.8 5.6L15 7l-4 3.6L12.2 16 8 12.8 3.8 16 '
            '5 10.6 1 7l5.2-1.4z"/>'
            "</svg>"
            "</span>"
            '<span class="poka-brand-text">'
            '<span class="poka-word">Poka</span>'
            '<span class="poka-sub">AI assistant</span>'
            "</span>"
            "</div>",
            unsafe_allow_html=True,
        )

        # ---- Active model (dynamic, subtle) ----
        model_name: str = _active_model_name()
        model_live: bool = _model_is_live(model_name)
        dot_class: str = "poka-dot-online" if model_live else "poka-dot-offline"
        st.markdown(
            '<div class="poka-model">'
            f'<span class="poka-dot {dot_class}" aria-hidden="true"></span>'
            f'<span class="poka-model-name">{html.escape(model_name)}</span>'
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown('<div class="poka-divider"></div>', unsafe_allow_html=True)

        # ---- New chat (key + behavior unchanged) ----
        if st.button(
            "+ New chat",
            type="primary",
            key="new-chat",
        ):

            archive_current_chat()

            st.session_state.messages = []

            persist()

            st.rerun()

        # ---- Search (key + behavior unchanged) ----
        search_q: str = st.text_input(
            "Search chat",
            placeholder="Search...",
            label_visibility="collapsed",
            key="chat-search",
        )
        if search_q.strip():
            match_count: int = sum(
                1
                for m in st.session_state.messages
                if search_q.lower() in str(m.get("content", "")).lower()
            )
            st.markdown(
                f'<p class="poka-match">{match_count} matches</p>',
                unsafe_allow_html=True,
            )

        # ---- Recents ----
        st.markdown(
            '<p class="section-label">Recents</p>',
            unsafe_allow_html=True,
        )

        if st.session_state.chats:

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

                        selected = (
                            st.session_state.chats.pop(i)
                        )

                        archive_current_chat()

                        st.session_state.messages = (
                            selected["messages"]
                        )

                        persist()

                        st.rerun()
                with pencil_col:
                    if st.button(
                        "⋯",
                        key=f"rename-{i}",
                        help="Rename chat",
                    ):
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

        else:
            st.markdown(
                '<p class="poka-empty">No recent conversations</p>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="poka-divider"></div>', unsafe_allow_html=True)

        # ---- Mode (single segmented control, same deep_mode state) ----
        # The active segment is disabled so it reads as selected; the
        # other segment switches mode. No second state is introduced.
        st.markdown('<p class="section-label">Mode</p>', unsafe_allow_html=True)
        is_deep: bool = bool(st.session_state.get("deep_mode", False))
        fast_col, deep_col = st.columns(2, gap="small")
        with fast_col:
            if st.button(
                "Fast",
                key="mode-fast",
                help="Fast mode",
                disabled=not is_deep,
            ):
                st.session_state.deep_mode = False
                st.rerun()
        with deep_col:
            if st.button(
                "Deep",
                key="mode-deep",
                help="Deep mode",
                disabled=is_deep,
            ):
                st.session_state.deep_mode = True
                st.rerun()

        # ---- Memory (keys + logic unchanged, card instead of expander) ----
        st.markdown(
            '<p class="section-label">Memory</p>',
            unsafe_allow_html=True,
        )
        with st.container(border=True):

            st.markdown(
                '<p class="poka-card-sub">Saved context</p>',
                unsafe_allow_html=True,
            )

            notes_in = st.text_area(
                "Memory notes",
                value=st.session_state.get(
                    "memory_notes",
                    "",
                ),
                height=80,
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
                if delete_memory_fact(forget_in):
                    st.toast("Forgotten.")
                else:
                    st.toast("Nothing matched that.")
                st.rerun()

        # ---- Files & stats (keys + logic unchanged, cards not expander) ----
        st.markdown(
            '<p class="section-label">Files</p>',
            unsafe_allow_html=True,
        )

        with st.container(border=True):

            try:
                owned_files = _file_store().list_outputs()
            except StorageError:
                owned_files = []

            if owned_files:

                for meta in owned_files[:5]:

                    safe_name: str = html.escape(meta.display_name)
                    st.markdown(
                        '<div class="poka-file-row">'
                        '<span class="poka-file-icon" aria-hidden="true">'
                        '<svg viewBox="0 0 16 16" width="14" height="14">'
                        '<path d="M3 1h5l4 4v10H3z" fill="none" '
                        'stroke="currentColor" stroke-width="1.3"/>'
                        '<path d="M8 1v4h4" fill="none" '
                        'stroke="currentColor" stroke-width="1.3"/>'
                        "</svg>"
                        "</span>"
                        f'<span class="poka-file-name">{safe_name}</span>'
                        "</div>",
                        unsafe_allow_html=True,
                    )

                    file_bytes = None
                    try:
                        file_bytes = _file_store().read_output(meta.id)
                    except StorageError:
                        file_bytes = None
                    if file_bytes is not None:
                        st.download_button(
                            "Download file",
                            file_bytes,
                            file_name=meta.display_name,
                            key=f"side-dl-{meta.id}",
                        )

            else:

                st.markdown(
                    '<p class="poka-empty">No files yet</p>',
                    unsafe_allow_html=True,
                )

        st.markdown(
            '<p class="section-label">Stats</p>',
            unsafe_allow_html=True,
        )

        with st.container(border=True):

            st.markdown(
                '<div class="stats-box">'
                '<div class="poka-stat-row">'
                '<span class="poka-stat-key">Messages</span>'
                f'<span class="poka-stat-val">'
                f'{len(st.session_state.messages)}'
                "</span>"
                "</div>"
                '<div class="poka-stat-row">'
                '<span class="poka-stat-key">Files</span>'
                f'<span class="poka-stat-val">'
                f'{len(owned_files)}'
                "</span>"
                "</div>"
                '<div class="poka-stat-row">'
                '<span class="poka-stat-key">Active</span>'
                f'<span class="poka-stat-active">'
                f'{html.escape(model_name)}'
                "</span>"
                "</div>"
                "</div>",
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

        # ---- Quiet footer (same dynamic source, no new state) ----
        st.markdown('<div class="poka-divider"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="poka-model poka-footer">'
            f'<span class="poka-dot {dot_class}" aria-hidden="true"></span>'
            f'<span class="poka-model-name">{html.escape(model_name)}</span>'
            "</div>",
            unsafe_allow_html=True,
        )

    return model_name
