"""Sidebar: brand, model status, mode, chats, memory, files, stats.

Page section only: persistence and stores come from
application.session, memory facts from services.memory. Returns the
active model name for the page footer.
"""

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
from ui.components import _export_chat_to_markdown, tier_status


def render_sidebar() -> str:
    """Render the full sidebar; return the active model name."""

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

        st.markdown("<hr style='border-color:#27273a;margin:16px 0;'>", unsafe_allow_html=True)
        st.markdown('<p class="section-label">Mode</p>', unsafe_allow_html=True)
        st.toggle("Deep Mode", key="deep-mode")
        mode_color = "#6366f1" if st.session_state.deep_mode else "#8b8b9e"
        mode_label = "Deep" if st.session_state.deep_mode else "Fast"
        st.markdown(
            f'<p style="color:{mode_color};font-size:12px;'
            'font-weight:600;text-align:center;">'
            f"{mode_label} Mode Active</p>",
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


        search_q: str = st.text_input(
            "Search chat",
            placeholder="Find in conversation...",
            label_visibility="collapsed",
            key="chat-search",
        )
        if search_q.strip():
            match_count: int = sum(
                1
                for m in st.session_state.messages
                if search_q.lower() in str(m.get("content", "")).lower()
            )
            st.caption(f"{match_count} matches")

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
                    if st.button("✎", key=f"rename-{i}"):
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

            try:
                owned_files = _file_store().list_outputs()
            except StorageError:
                owned_files = []

            if owned_files:

                for meta in owned_files[:5]:

                    st.markdown(
                        f'<div class="file-card">'
                        f'{meta.display_name}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    file_bytes = None
                    try:
                        file_bytes = _file_store().read_output(meta.id)
                    except StorageError:
                        file_bytes = None
                    if file_bytes is not None:
                        st.download_button(
                            "Get file",
                            file_bytes,
                            file_name=meta.display_name,
                            key=f"side-dl-{meta.id}",
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
                f'{len(owned_files)}'
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

    return model_name
