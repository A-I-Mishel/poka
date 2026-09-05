"""Chat rendering and message flow: history display, send, edit, retry.

Operates on Streamlit session state; answering goes through
application.session.run_agent (rate-limited) and persistence through
application.session.persist. No direct service construction here.
"""

import html
import os
import time
from typing import Any, Dict, List

import streamlit as st

from application.session import (
    _file_store,
    build_chat_history,
    persist,
    run_agent,
)
from services.files import FileValidationError
from services.storage import StorageError
from services.timeutil import utcnow_iso
from ui.components import _format_time, _highlight_query, _show_typing


_POKA_MARK_SVG: str = (
    '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">'
    '<path d="M8 0l1.8 5.6L15 7l-4 3.6L12.2 16 8 12.8 3.8 16 '
    '5 10.6 1 7l5.2-1.4z"/>'
    "</svg>"
)

_POKA_ASSISTANT_ID: str = (
    '<div class="poka-assistant-id">'
    f'<span class="poka-assistant-mark">{_POKA_MARK_SVG}</span>'
    "<span>Poka</span>"
    "</div>"
)


def _meta_row(msg_time: str) -> str:
    """Subtle metadata row (time only; actions are existing widgets)."""
    if not msg_time:
        return ""
    return (
        '<div class="poka-meta">'
        f'<span class="poka-time">{html.escape(msg_time)}</span>'
        "</div>"
    )


def render_history() -> None:
    """Render the conversation with search highlighting and edit buttons."""
    search_text: str = str(st.session_state.get("chat-search", "") or "")
    for idx, msg in enumerate(st.session_state.messages):

        is_user: bool = isinstance(msg, dict) and msg.get("role") == "user"

        with st.chat_message(msg["role"]):

            if msg.get("role") == "assistant":
                st.markdown(_POKA_ASSISTANT_ID, unsafe_allow_html=True)

            if (
                msg.get("image")
                and os.path.exists(
                    str(msg["image"])
                )
            ):
                st.image(
                    str(msg["image"]),
                    width=320,
                )

            st.markdown(
                _highlight_query(str(msg.get("content", "")), search_text)
            )
            msg_time: str = _format_time(str(msg.get("time", "")))
            meta_html: str = _meta_row(msg_time)

            if is_user:
                # Time + Edit share one action row inside the user
                # bubble so Edit reads as a message action.
                meta_col, edit_col = st.columns(
                    [4, 1],
                    vertical_alignment="center",
                )
                with meta_col:
                    if meta_html:
                        st.markdown(meta_html, unsafe_allow_html=True)
                with edit_col:
                    if st.button(
                        "Edit", key=f"edit-{idx}", help="Edit message"
                    ):
                        old_text: str = str(msg.get("content", ""))
                        old_atts = msg.get("attachments")
                        restored = None
                        if isinstance(old_atts, list):
                            for candidate in old_atts:
                                if isinstance(candidate, dict) and candidate.get(
                                    "id"
                                ):
                                    restored = {
                                        "upload_id": str(candidate["id"]),
                                        "kind": str(
                                            candidate.get("kind", "image")
                                        ),
                                        "name": str(
                                            candidate.get("name", "file")
                                        ),
                                        "mark": [
                                            "restored",
                                            str(candidate["id"]),
                                        ],
                                    }
                                    break
                        st.session_state.messages = st.session_state.messages[
                            :idx
                        ]
                        st.session_state[
                            f"composer_input_{st.session_state.composer_key}"
                        ] = old_text
                        st.session_state.pending_attach = restored
                        persist()
                        st.rerun()
            elif meta_html:
                st.markdown(meta_html, unsafe_allow_html=True)


def render_assistant_response(
    user_text: str,
) -> None:
    """Append user text and render assistant reply."""

    attach = st.session_state.pop(
        "pending_attach",
        None,
    )

    # One-shot toggle: the agent enforces the search as policy (see run_agent).
    st.session_state.force_search = False

    send_text: str = user_text

    image_path: Any = None
    image_ids: List[str] = []
    attachments: List[Dict[str, str]] = []

    if isinstance(attach, dict):

        kind: str = str(
            attach.get("kind", "")
        )
        upload_id: str = str(attach.get("upload_id", ""))
        disp_name: str = str(attach.get("name", "file"))
        if upload_id:
            attachments.append({"id": upload_id, "kind": kind, "name": disp_name})

        if kind == "pdf":

            send_text += (
                f"\n\n[Attached PDF '{disp_name}' with upload ID: {upload_id}. "
                "To read it, call read_pdf(upload_id=\""
                f"{upload_id}"
                "\"). Never use any other path or ID.]"
            )

        elif kind == "csv":

            send_text += (
                f"\n\n[Attached CSV '{disp_name}' with upload ID: {upload_id}. "
                "To analyze it, call analyze_csv(upload_id=\""
                f"{upload_id}"
                "\"). Never use any other path or ID.]"
            )

        else:

            try:
                resolved = _file_store().resolve_upload(upload_id) if upload_id else None
            except (StorageError, FileValidationError):
                resolved = None
            image_path = str(resolved) if resolved is not None else None
            if upload_id:
                image_ids.append(upload_id)

            send_text += (
                f"\n\n[Attached image: {disp_name}. "
                "You cannot view images; if asked "
                "about its contents, say so briefly "
                "and continue helping from the text.]"
            )

    user_msg: Dict[str, Any] = {
        "role": "user",
        "content": user_text,
        "time": utcnow_iso(),
    }
    if attachments:
        user_msg["attachments"] = attachments

    if image_path:
        user_msg["image"] = str(image_path)

    prior_history = build_chat_history(st.session_state.messages)
    prior_raw: List[Dict[str, Any]] = [
        dict(m) for m in st.session_state.messages if isinstance(m, dict)
    ]

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
                width=320,
            )

        st.markdown(user_text)

    with st.chat_message("assistant"):

        st.markdown(_POKA_ASSISTANT_ID, unsafe_allow_html=True)

        typing_box = _show_typing()

        try:

            request_started: float = time.time()

            output: str = run_agent(
                send_text,
                history=prior_history,
                raw_messages=prior_raw,
                image_ids=image_ids,
            )

            typing_box.empty()

            st.markdown(output)

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": output,
                    "time": utcnow_iso(),
                }
            )

            st.session_state.pop("last_failed", None)

            persist()

            try:
                fresh_files = [
                    m for m in _file_store().list_outputs()
                    if m.created >= request_started
                ]
            except StorageError:
                fresh_files = []
            for meta in fresh_files:
                try:
                    file_bytes = _file_store().read_output(meta.id)
                except StorageError:
                    file_bytes = None
                if file_bytes is None:
                    continue
                st.download_button(
                    f"Download {meta.display_name}",
                    file_bytes,
                    file_name=meta.display_name,
                    key=(
                        f"dl-{meta.id}-"
                        f"{len(st.session_state.messages)}"
                    ),
                )

        except Exception as e:

            typing_box.empty()

            st.session_state.last_failed = send_text

            st.error(f"Error: {e}")


def _retry_last() -> None:
    """Re-run the last failed request without duplicating the user message."""
    send_text = st.session_state.pop("last_failed", None)
    if not send_text:
        return
    prior = list(st.session_state.messages)
    retry_history = build_chat_history(prior[:-1] if prior else [])
    retry_raw: List[Dict[str, Any]] = [
        dict(m) for m in (prior[:-1] if prior else []) if isinstance(m, dict)
    ]
    with st.chat_message("assistant"):
        st.markdown(_POKA_ASSISTANT_ID, unsafe_allow_html=True)
        typing_box = _show_typing()
        try:
            output: str = run_agent(
                str(send_text),
                history=retry_history,
                raw_messages=retry_raw,
            )
            typing_box.empty()
            st.markdown(output)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": output,
                    "time": utcnow_iso(),
                }
            )
            persist()
        except Exception as e:
            typing_box.empty()
            st.session_state.last_failed = send_text
            st.error(f"Error: {e}")
            st.rerun()
