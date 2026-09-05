"""Attachment UI: pending-attachment chip and the plus-menu pickers.

Staging itself lives in application.session._stage_upload; this module
only renders widgets and forwards uploader values to it.
"""

import html

import streamlit as st

from application.session import _stage_upload


_DOC_SVG: str = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<path d="M3 1h5l4 4v10H3z" fill="none" '
    'stroke="currentColor" stroke-width="1.3"/>'
    '<path d="M8 1v4h4" fill="none" '
    'stroke="currentColor" stroke-width="1.3"/>'
    "</svg>"
)

_TABLE_SVG: str = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<rect x="2" y="2.5" width="12" height="11" rx="1.5" fill="none" '
    'stroke="currentColor" stroke-width="1.3"/>'
    '<path d="M2 6.5h12M7 6.5v7" fill="none" '
    'stroke="currentColor" stroke-width="1.3"/>'
    "</svg>"
)

_IMAGE_SVG: str = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<rect x="2" y="2.5" width="12" height="11" rx="1.5" fill="none" '
    'stroke="currentColor" stroke-width="1.3"/>'
    '<circle cx="5.5" cy="6.5" r="1.3" fill="currentColor"/>'
    '<path d="M2.5 12.5l3.5-3.5 2.5 2.5 2-2 3 3" fill="none" '
    'stroke="currentColor" stroke-width="1.3"/>'
    "</svg>"
)

_SPARK_SVG: str = (
    '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">'
    '<path d="M8 0l1.8 5.6L15 7l-4 3.6L12.2 16 8 12.8 3.8 16 '
    '5 10.6 1 7l5.2-1.4z"/>'
    "</svg>"
)


def _kind_icon(kind: str) -> str:
    """File-type icon for the chip (visual only; kind logic unchanged)."""
    if kind == "pdf":
        return _DOC_SVG
    if kind == "csv":
        return _TABLE_SVG
    return _IMAGE_SVG


def render_attachment_chip() -> None:
    """Show (or clear) the pending-attachment chip and search notice."""
    pending = st.session_state.get(
        "pending_attach"
    )

    if isinstance(pending, dict):
        chip_text, chip_x = st.columns(
            [5, 1],
            vertical_alignment="center",
        )

        chip_text.markdown(
            '<div class="poka-chips">'
            '<div class="poka-chip">'
            '<span class="poka-chip-icon" aria-hidden="true">'
            + _kind_icon(str(pending.get("kind", "image")))
            + "</span>"
            '<span class="poka-chip-name">'
            + html.escape(
                str(
                    pending.get(
                        "name",
                        "file",
                    )
                )
            )
            + "</span>"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        if chip_x.button(
            "x",
            key="rm-attach",
            help="Remove attachment",
        ):

            st.session_state.pending_attach = None

            st.rerun()

    elif st.session_state.get(
        "force_search"
    ):

        st.markdown(
            '<div class="poka-chips">'
            '<span class="poka-search-pill">'
            '<span class="poka-search-mark" aria-hidden="true">'
            + _SPARK_SVG
            + "</span>"
            "Web search will be used"
            "</span>"
            "</div>",
            unsafe_allow_html=True,
        )


def render_attachment_menu() -> None:
    """Render the plus-menu: file picker, camera, and web-search toggle."""
    if st.session_state.get(
        "show_attach_menu",
        False,
    ):

        # Keyed container gives the menu a stable wrapper class
        # (st-key-attachment-menu) for anchoring; widget keys unchanged.
        with st.container(key="attachment-menu"):

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
