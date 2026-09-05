"""Attachment UI: pending-attachment chip and the plus-menu pickers.

Staging itself lives in application.session._stage_upload; this module
only renders widgets and forwards uploader values to it.
"""

import html

import streamlit as st

from application.session import _stage_upload


def render_attachment_chip() -> None:
    """Show (or clear) the pending-attachment chip and search notice."""
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


def render_attachment_menu() -> None:
    """Render the plus-menu: file picker, camera, and web-search toggle."""
    if st.session_state.get(
        "show_attach_menu",
        False,
    ):

        with st.container():

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
                "Take a photo",
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
                    "Take a photo",
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
