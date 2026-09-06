"""Attachment UI: pending-attachment chip and the plus-menu pickers.

Staging itself lives in application.session._stage_upload; this module
only renders widgets and forwards uploader values to it.
"""

import html

import streamlit as st

from application.session import (
    _attachment_append,
    _file_store,
    _pending_list,
    _set_pending_list,
    _stage_upload,
)


RECENT_VISIBLE = 5


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


def _recent_tag(kind: str) -> str:
    """Stable menu-key tag for an upload kind (never invented kinds)."""
    if kind == "pdf":
        return "pdf"
    if kind == "csv":
        return "csv"
    return "img"


def _recent_kind_label(kind: str) -> str:
    """Human label for an upload kind."""
    if kind == "pdf":
        return "PDF"
    if kind == "csv":
        return "CSV"
    return "Image"


def _recent_uploads() -> list:
    """Owned uploads that are still resolvable, newest first.

    Registry is the source of truth; entries whose bytes are gone
    (pruned/removed) are omitted so the menu never shows broken rows.
    Never raises.
    """
    try:
        metas = _file_store().list_uploads()
    except Exception:
        return []
    valid = []
    for meta in metas:
        try:
            if _file_store().resolve_upload(meta.id) is None:
                continue
        except Exception:
            continue
        valid.append(meta)
    return valid


def _reuse_upload(upload_id: str) -> str:
    """Append an owned upload to the pending attachments (no copy/re-upload).

    Returns "" on success (including idempotent re-selects), otherwise a
    user-safe reason. Validates ownership through the existing
    get_upload/resolve_upload checks; refuses foreign, malformed, or
    missing files without raising. Respects the shared attachment caps;
    over-limit selections fail without disturbing the pending set.
    """
    try:
        meta = _file_store().get_upload(upload_id)
    except Exception:
        meta = None
    if meta is None:
        return "That file is no longer available."
    try:
        resolved = _file_store().resolve_upload(meta.id)
    except Exception:
        resolved = None
    if resolved is None:
        return "That file is no longer available."
    updated, error = _attachment_append(
        _pending_list(),
        {
            "upload_id": meta.id,
            "kind": meta.kind,
            "name": meta.display_name,
            "path": meta.display_name,
            "mark": ["recent", meta.id],
        },
    )
    if error:
        return error
    _set_pending_list(updated)
    return ""


def render_attachment_chip() -> None:
    """Show (or clear) pending-attachment chips and search notice."""
    pending_items = _pending_list()

    if pending_items:
        for _item in pending_items:
            _item_id = str(_item.get("upload_id", ""))
            _item_kind = str(_item.get("kind", "image"))
            _item_name = str(_item.get("name", "file"))
            chip_text, chip_x = st.columns(
                [5, 1],
                vertical_alignment="center",
            )

            chip_text.markdown(
                '<div class="poka-chips">'
                '<div class="poka-chip">'
                '<span class="poka-chip-icon" aria-hidden="true">'
                + _kind_icon(_item_kind)
                + "</span>"
                '<span class="poka-chip-name" title="'
                + html.escape(_item_name)
                + '">'
                + html.escape(_item_name)
                + "</span>"
                "</div>"
                "</div>",
                unsafe_allow_html=True,
            )

            # Escape like sidebar _md_text: tooltips render markdown.
            _item_safe = html.escape(_item_name).replace("[", "\\[")
            if chip_x.button(
                "x",
                key=f"rm-attach-{_item_id}",
                help=f"Remove {_item_safe}",
            ):

                _set_pending_list([
                    e for e in _pending_list()
                    if str(e.get("upload_id", "")) != _item_id
                ])

                st.rerun()

        if len(pending_items) == 1:
            _only = pending_items[0]
            _ready_text = {
                "pdf": "PDF staged — ask questions or request a summary.",
                "csv": "CSV staged — ask for analysis or specific numbers.",
                "image": "Image staged — ask what you need from it.",
            }.get(
                str(_only.get("kind", "image")),
                "File staged — ask what you need from it.",
            )
        else:
            _ready_text = (
                f"{len(pending_items)} files staged — "
                "ask about any of them."
            )
        st.caption(_ready_text)

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

            st.markdown(
                '<p class="poka-menu-head">Add files or photos</p>',
                unsafe_allow_html=True,
            )

            if st.button(
                "Upload",
                key="menu-files",
            ):

                st.session_state.attach_menu = (
                    None
                    if st.session_state.attach_menu
                    == "files"
                    else "files"
                )

                st.rerun()

            st.markdown(
                '<p class="poka-menu-sub">'
                "200MB per file \u2022 PDF, CSV, PNG, JPG"
                "</p>",
                unsafe_allow_html=True,
            )


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

            st.markdown(
                '<p class="poka-menu-head">Recent files</p>',
                unsafe_allow_html=True,
            )

            _recents = _recent_uploads()

            if not _recents:
                st.markdown(
                    '<p class="poka-menu-sub">No uploaded files yet. '
                    "Upload a file to reuse it here.</p>",
                    unsafe_allow_html=True,
                )
            else:
                _staged_ids = {
                    str(e.get("upload_id", ""))
                    for e in _pending_list()
                }
                for _meta in _recents[:RECENT_VISIBLE]:
                    _tag = _recent_tag(str(_meta.kind))
                    _label = (
                        ("✓ " if _meta.id in _staged_ids else "")
                        + str(_meta.display_name)
                    )
                    if st.button(
                        _label,
                        key=f"recent-{_tag}-{_meta.id}",
                        help=(
                            f"{_recent_kind_label(str(_meta.kind))} "
                            "— reuse this file"
                        ),
                    ):
                        # Stay open for multi-select; the ✓ marker and
                        # chips show what is already staged.
                        _reuse_error = _reuse_upload(_meta.id)
                        if _reuse_error:
                            st.toast(_reuse_error)
                        st.rerun()
                if len(_recents) > RECENT_VISIBLE:
                    st.markdown(
                        '<p class="poka-menu-sub">'
                        f"+{len(_recents) - RECENT_VISIBLE} more files"
                        "</p>",
                        unsafe_allow_html=True,
                    )
