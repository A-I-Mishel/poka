"""Chat rendering and message flow: history display, send, edit, retry.

Operates on Streamlit session state; answering goes through
application.session.run_agent (rate-limited) and persistence through
application.session.persist. No direct service construction here.
"""

import html
import os
from typing import Any, Dict, List

import streamlit as st

from application.session import (
    _file_store,
    _pending_list,
    _set_pending_list,
    _user_store,
    build_chat_history,
    ensure_current_chat_id,
    get_active_project_context,
    persist,
    run_agent,
)
from services.files import FileValidationError
from services.storage import StorageError, clean_source_record
from services.timeutil import utcnow_iso
from services import research as research_svc
from ui.components import (
    _artifact_card_html,
    _artifact_sub_for,
    _format_time,
    _highlight_query,
    _show_typing,
)
from ui.uploads import _kind_icon


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


def _file_row_html(kind: str, name: str) -> str:
    """Compact file association row (visual only; data comes from
    the message's stored attachments)."""
    return (
        '<div class="poka-msg-file">'
        '<div class="poka-file-row">'
        '<span class="poka-file-icon" aria-hidden="true">'
        + _kind_icon(kind)
        + "</span>"
        '<span class="poka-file-name" title="'
        + html.escape(name)
        + '">'
        + html.escape(name)
        + "</span>"
        "</div>"
        "</div>"
    )


def _non_image_attachments(msg: Dict[str, Any]) -> List[Dict[str, str]]:
    """Stored PDF/CSV attachments (images already render via st.image)."""
    atts = msg.get("attachments")
    if not isinstance(atts, list):
        return []
    return [
        a for a in atts
        if isinstance(a, dict) and a.get("id") and a.get("kind") != "image"
    ]


def _known_output_ids() -> set:
    """IDs in this user's output registry right now (never raises)."""
    try:
        return {m.id for m in _file_store().list_outputs()}
    except Exception:
        return set()


def _outputs_since(before: set) -> list:
    """Registry entries created after the snapshot, newest first.

    Explicit set-difference linkage: no timestamps, filename matching,
    or ordering heuristics.
    """
    try:
        metas = _file_store().list_outputs()
    except Exception:
        return []
    if not isinstance(before, set):
        return []
    return [m for m in metas if m.id not in before]


def _linked_artifacts(msg: Any) -> list:
    """Validated [{id,kind,name}] artifact links stored on a message."""
    if not isinstance(msg, dict):
        return []
    links = msg.get("artifacts")
    if not isinstance(links, list):
        return []
    clean = []
    for entry in links:
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and entry["id"]
            and entry.get("kind") in ("pptx", "docx", "file")
            and isinstance(entry.get("name"), str)
            and entry["name"]
        ):
            clean.append({
                "id": entry["id"],
                "kind": entry["kind"],
                "name": entry["name"][:120],
            })
    return clean[:8]


def _artifact_sub(meta: Any) -> str:
    """One-line kind/size/date summary from a live registry record."""
    return _artifact_sub_for(
        getattr(meta, "kind", ""), getattr(meta, "display_name", ""),
        getattr(meta, "size", None), getattr(meta, "created", None),
    )


def _render_message_artifact(entry_id: str, entry_kind: str,
                             entry_name: str, key: str,
                             message_idx: int = -1) -> None:
    """Artifact row + download for one linked output (graceful when gone).

    Artifacts with a valid stored spec also offer Regenerate, which
    re-runs the saved spec into a NEW artifact (original preserved).
    Legacy artifacts without specs stay download-only.
    """
    try:
        data = _file_store().read_output(entry_id)
    except StorageError:
        data = None
    meta = None
    if data is not None:
        try:
            meta = _file_store().get_output(entry_id)
        except StorageError:
            meta = None
    if data is None or meta is None:
        st.markdown(
            _artifact_card_html(entry_name, entry_kind, "Expired",
                                expired=True),
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        _artifact_card_html(
            meta.display_name, meta.kind, _artifact_sub(meta)),
        unsafe_allow_html=True,
    )
    st.download_button(
        f"Download {meta.display_name}",
        data,
        file_name=meta.display_name,
        key=key,
    )
    # Regeneration: only for owned artifacts with a valid spec.
    try:
        _can_regen = research_svc.can_regenerate(_file_store(), entry_id)
    except Exception:
        _can_regen = False
    if _can_regen:
        _regen_key = f"regen-chat-{entry_id}-{message_idx}"
        if st.button("Regenerate", key=_regen_key,
                     help="Creates a new artifact using the saved "
                     "generation settings."):
            try:
                _before = {m.id for m in _file_store().list_outputs()}
            except Exception:
                _before = set()
            try:
                _new_meta = research_svc.regenerate_artifact(
                    _file_store(), entry_id)
            except ValueError as e:
                st.toast(str(e)[:200])
            except RuntimeError as e:
                st.toast(str(e)[:200])
            except Exception:
                st.toast("Could not regenerate this file.")
            else:
                # Link the new artifact to the same open message so the
                # project derived view keeps both outputs together.
                try:
                    _msgs = st.session_state.get("messages", [])
                    if (isinstance(_msgs, list) and 0 <= message_idx
                            and message_idx < len(_msgs)
                            and isinstance(_msgs[message_idx], dict)):
                        _arts = _msgs[message_idx].get("artifacts")
                        if not isinstance(_arts, list):
                            _msgs[message_idx]["artifacts"] = []
                        _msgs[message_idx]["artifacts"].append({
                            "id": _new_meta.id, "kind": _new_meta.kind,
                            "name": _new_meta.display_name,
                        })
                        st.session_state.messages = _msgs
                        persist()
                    else:
                        persist()
                except Exception:
                    pass
                st.toast("Regenerated as a new file.")
                st.rerun()


def _assistant_meta(searched: bool) -> Dict[str, Any]:
    """Response metadata for the request just executed.

    Every value is locally known, never inferred: model is the tier that
    just succeeded (run_agent records it), mode is the effective request
    mode, searched is the captured one-shot intent, search_executed is
    derived from actually-recorded tool use, tools/sources are what
    run_agent stashed for this exact call (possibly empty).
    """
    meta: Dict[str, Any] = {
        "mode": "deep" if st.session_state.get("deep_mode", False) else "fast",
        "searched": bool(searched),
    }
    model = str(st.session_state.get("active_tier", "") or "")
    if model:
        meta["model"] = model
    stashed_tools = st.session_state.get("_last_tools_used", [])
    tool_names: List[str] = []
    if isinstance(stashed_tools, list):
        tool_names = [t for t in stashed_tools if isinstance(t, str) and t]
    meta["search_executed"] = "web_search" in tool_names
    if tool_names:
        meta["tools"] = tool_names
    stashed_sources = st.session_state.get("_last_sources", [])
    if isinstance(stashed_sources, list):
        records = [dict(s) for s in stashed_sources if isinstance(s, dict)]
        if records:
            meta["sources"] = records
    return meta


def _meta_row(msg: Any) -> str:
    """Subtle metadata row: time plus persisted response facts (if any).

    Only shows what is actually stored. Legacy messages without metadata
    render exactly as before (time only); nothing is ever inferred.
    """
    if not isinstance(msg, dict):
        return ""
    bits: List[str] = []
    msg_time: str = _format_time(str(msg.get("time", "")))
    if msg_time:
        bits.append(html.escape(msg_time))
    model = msg.get("model")
    if isinstance(model, str) and model:
        bits.append(html.escape(model))
    if msg.get("mode") == "deep":
        bits.append("Deep")
    # Execution only: forced intent alone (searched) never earns the
    # label — the flag may be set while the search itself failed.
    if msg.get("search_executed") is True:
        bits.append("Web search")
    tools = msg.get("tools")
    if isinstance(tools, list):
        names = [t for t in tools if isinstance(t, str) and t]
        if names:
            bits.append("1 tool" if len(names) == 1 else f"{len(names)} tools")
    if not bits:
        return ""
    return (
        '<div class="poka-meta">'
        '<span class="poka-time">' + " · ".join(bits) + "</span>"
        "</div>"
    )


def _sources_section(msg: Any) -> str:
    """Compact source list from PERSISTED provenance (never markdown).

    Records are re-validated on every render, so tampered or legacy
    shapes can never produce unsafe links. http(s) only.
    """
    if not isinstance(msg, dict):
        return ""
    stored = msg.get("sources")
    if not isinstance(stored, list):
        return ""
    records = []
    for entry in stored:
        cleaned = clean_source_record(entry)
        if cleaned is not None:
            records.append(cleaned)
        if len(records) >= 6:
            break
    if not records:
        return ""
    parts = [
        '<div class="poka-sources">',
        '<p class="poka-sources-head">Sources</p>',
    ]
    for idx, record in enumerate(records, start=1):
        href = record["url"].replace(")", "%29")
        parts.append(
            '<p class="poka-source">'
            f'<span class="poka-source-n">[{idx}]</span> '
            f'<a href="{html.escape(href, quote=True)}" '
            'target="_blank" rel="noopener noreferrer">'
            f"{html.escape(record['title'])}</a> "
            f'<span class="poka-source-d">'
            f"{html.escape(record['domain'])}</span>"
            "</p>"
        )
    parts.append("</div>")
    return "".join(parts)


def render_history() -> None:
    """Render the conversation with search highlighting and edit buttons."""
    search_text: str = str(st.session_state.get("chat-search", "") or "")
    for idx, msg in enumerate(st.session_state.messages):

        is_user: bool = isinstance(msg, dict) and msg.get("role") == "user"

        with st.chat_message(msg["role"]):

            if msg.get("role") == "assistant":
                st.markdown(_POKA_ASSISTANT_ID, unsafe_allow_html=True)

            if is_user:
                for _att in _non_image_attachments(msg):
                    st.markdown(
                        _file_row_html(
                            str(_att.get("kind", "image")),
                            str(_att.get("name", "file")),
                        ),
                        unsafe_allow_html=True,
                    )

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
                _shown_images = {str(msg["image"])}
            else:
                _shown_images = set()

            if is_user:
                for _att in (msg.get("attachments") or []):
                    if (
                        not isinstance(_att, dict)
                        or _att.get("kind") != "image"
                        or not _att.get("id")
                    ):
                        continue
                    try:
                        _resolved = _file_store().resolve_upload(
                            str(_att["id"]))
                    except (StorageError, FileValidationError):
                        _resolved = None
                    if _resolved is None:
                        continue
                    _resolved_str = str(_resolved)
                    if _resolved_str in _shown_images:
                        continue
                    if not os.path.exists(_resolved_str):
                        continue
                    _shown_images.add(_resolved_str)
                    st.image(
                        _resolved_str,
                        width=320,
                    )

            st.markdown(
                _highlight_query(str(msg.get("content", "")), search_text)
            )
            if not is_user:
                sources_html: str = _sources_section(msg)
                if sources_html:
                    st.markdown(sources_html, unsafe_allow_html=True)
                for _entry in _linked_artifacts(msg):
                    _render_message_artifact(
                        _entry["id"], _entry["kind"], _entry["name"],
                        f"dl-{_entry['id']}-{idx}",
                        message_idx=idx,
                    )
                # Save as brief: only for search-backed answers with
                # trustworthy structured provenance (never markdown).
                # Query comes from the nearest preceding user message;
                # when it cannot be recovered the action stays hidden.
                try:
                    _eligible = research_svc.is_brief_eligible(msg)
                except Exception:
                    _eligible = False
                if _eligible:
                    try:
                        _recoverable = research_svc.find_brief_query(
                            st.session_state.messages, idx) is not None
                    except Exception:
                        _recoverable = False
                    if _recoverable:
                        _saved_key = f"brief-saved-{idx}"
                        try:
                            _already_saved = bool(
                                st.session_state.get(_saved_key, False))
                        except Exception:
                            _already_saved = False
                        if _already_saved:
                            st.markdown("Saved as Research Brief")
                        else:
                            if st.button(
                                "Save as brief",
                                key=f"save-brief-{idx}",
                                help="Save this research answer as a brief",
                            ):
                                try:
                                    _record = research_svc.create_brief_from_message(
                                        _user_store(),
                                        st.session_state.messages,
                                        idx,
                                        st.session_state.get(
                                            "current_project_id", None),
                                    )
                                except ValueError as e:
                                    st.toast(str(e)[:200])
                                except StorageError as e:
                                    st.toast(f"Could not save brief: {e}"[:200])
                                except Exception:
                                    st.toast("Could not save brief.")
                                else:
                                    try:
                                        st.session_state[_saved_key] = True
                                    except Exception:
                                        pass
                                    st.toast("Saved as Research Brief")
                                    st.rerun()
            meta_html: str = _meta_row(msg)

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
                        restored_items: List[Dict[str, str]] = []
                        if isinstance(old_atts, list):
                            for candidate in old_atts:
                                if isinstance(candidate, dict) and candidate.get(
                                    "id"
                                ):
                                    restored_items.append({
                                        "upload_id": str(candidate["id"]),
                                        "kind": str(
                                            candidate.get("kind", "image")
                                        ),
                                        "name": str(
                                            candidate.get("name", "file")
                                        ),
                                        "path": str(
                                            candidate.get("name", "file")
                                        ),
                                        "mark": [
                                            "restored",
                                            str(candidate["id"]),
                                        ],
                                    })
                        st.session_state.messages = st.session_state.messages[
                            :idx
                        ]
                        st.session_state[
                            f"composer_input_{st.session_state.composer_key}"
                        ] = old_text
                        _set_pending_list(restored_items)
                        persist()
                        st.rerun()
            elif meta_html:
                st.markdown(meta_html, unsafe_allow_html=True)

            if not is_user and idx == len(st.session_state.messages) - 1:
                # Regenerate offers a fresh answer to the latest exchange
                # only; the earlier answer is kept, never replaced. Sets a
                # flag handled by the page flow (same pattern as Retry).
                if st.button(
                    "Regenerate",
                    key=f"regen-msg-{idx}",
                    help="Generate a new response to the latest message",
                ):
                    st.session_state.do_regen = True
                    st.rerun()


# Intentional UI shortcuts (not AI-generated): each fills the existing
# composer input via the same composer_key mechanism as suggestion cards
# and Edit restore. Sending still goes through the normal send flow.
_FOLLOWUPS = (
    (
        "Summarize",
        "Summarize the above in 3 bullet points",
        "Fill the composer with a summary request",
    ),
    (
        "Simplify",
        "Explain the above more simply",
        "Fill the composer with a simplify request",
    ),
    (
        "Example",
        "Give me a concrete example of the above",
        "Fill the composer with an example request",
    ),
    (
        "Table",
        "Turn the key points above into a table",
        "Fill the composer with a table request",
    ),
)


def render_followups() -> None:
    """Follow-up shortcuts (retired; kept as a no-op for compatibility).

    Previously rendered Summarize/Simplify/Example/Table shortcut chips
    under the latest assistant reply. Removed per design request —
    app.py still calls this, so the name stays valid and does nothing.
    """
    return


def _attachment_hint(entry: Dict[str, Any], index: int, total: int) -> str:
    """Tool hint for one staged attachment (ID-only, never paths).

    Single-attachment text is byte-identical to the historical format.
    Multi-attachment blocks carry a stable [i/N] index; filenames may
    collide, upload IDs never do.
    """
    kind: str = str(entry.get("kind", ""))
    upload_id: str = str(entry.get("upload_id", ""))
    disp_name: str = str(entry.get("name", "file"))
    tag: str = "" if total <= 1 else f" {index}/{total}"
    if kind == "pdf":
        return (
            f"\n\n[Attached PDF{tag} '{disp_name}' with upload ID: {upload_id}. "
            "To read it, call read_pdf(upload_id=\""
            f"{upload_id}"
            "\"). Never use any other path or ID.]"
        )
    if kind == "csv":
        return (
            f"\n\n[Attached CSV{tag} '{disp_name}' with upload ID: {upload_id}. "
            "To analyze it, call analyze_csv(upload_id=\""
            f"{upload_id}"
            "\"). Never use any other path or ID.]"
        )
    return (
        f"\n\n[Attached image{tag}: {disp_name}. "
        "You cannot view images; if asked "
        "about its contents, say so briefly "
        "and continue helping from the text.]"
    )


def _attachments_overview(entries: List[Dict[str, Any]]) -> str:
    """One-line multi-file header so the model can map files to blocks."""
    labels = {
        "pdf": "PDF",
        "csv": "CSV",
    }
    parts = [
        f"'{str(e.get('name', 'file'))}' "
        f"({labels.get(str(e.get('kind', '')), 'Image')})"
        for e in entries
    ]
    return (
        f"\n\n[Attached files ({len(entries)}): "
        + ", ".join(parts)
        + ". Details per file below.]"
    )


def render_assistant_response(
    user_text: str,
) -> None:
    """Append user text and render assistant reply."""

    staged = _pending_list()
    _set_pending_list([])

    # One-shot toggle: capture this request's intent BEFORE clearing, so
    # run_agent receives the value even though the session flag is reset
    # here to keep later messages normal. Passed explicitly below.
    force_search = bool(st.session_state.get("force_search", False))
    st.session_state.force_search = False

    send_text: str = user_text

    image_paths: List[str] = []
    image_ids: List[str] = []
    attachments: List[Dict[str, str]] = []

    total = len(staged)
    if total > 1:
        send_text += _attachments_overview(staged)

    for position, attach in enumerate(staged, start=1):
        if not isinstance(attach, dict):
            continue

        kind: str = str(
            attach.get("kind", "")
        )
        upload_id: str = str(attach.get("upload_id", ""))
        disp_name: str = str(attach.get("name", "file"))
        if not upload_id:
            continue
        attachments.append({"id": upload_id, "kind": kind, "name": disp_name})

        if kind == "pdf" or kind == "csv":

            send_text += _attachment_hint(attach, position, total)

        else:

            try:
                resolved = _file_store().resolve_upload(upload_id)
            except (StorageError, FileValidationError):
                resolved = None
            if resolved is not None:
                image_paths.append(str(resolved))
            image_ids.append(upload_id)

            send_text += _attachment_hint(attach, position, total)

    user_msg: Dict[str, Any] = {
        "role": "user",
        "content": user_text,
        "time": utcnow_iso(),
    }
    if attachments:
        user_msg["attachments"] = attachments

    if image_paths:
        user_msg["image"] = str(image_paths[0])

    prior_history = build_chat_history(st.session_state.messages)
    prior_raw: List[Dict[str, Any]] = [
        dict(m) for m in st.session_state.messages if isinstance(m, dict)
    ]

    st.session_state.messages.append(
        user_msg
    )

    # First message creates the open conversation's stable identity and,
    # only then, adopts the active project. Later sends never reassign:
    # browsing the sidebar must not silently move the open chat.
    if len(st.session_state.messages) == 1:
        ensure_current_chat_id()
        try:
            _active_pid = st.session_state.get("active_project_id", None)
        except Exception:
            _active_pid = None
        if isinstance(_active_pid, str) and _active_pid:
            try:
                _active_rec = _user_store().get_project(_active_pid)
            except Exception:
                _active_rec = None
            if isinstance(_active_rec, dict) and not _active_rec.get(
                    "archived", False):
                st.session_state.current_project_id = _active_rec["id"]
            else:
                st.session_state.current_project_id = None
        else:
            try:
                st.session_state.current_project_id = None
            except Exception:
                pass
    else:
        ensure_current_chat_id()

    with st.chat_message("user"):

        for _entry in [a for a in attachments if a["kind"] != "image"]:
            st.markdown(
                _file_row_html(
                    _entry["kind"],
                    _entry["name"],
                ),
                unsafe_allow_html=True,
            )

        for _path in image_paths:
            if os.path.exists(_path):
                st.image(
                    _path,
                    width=320,
                )

        st.markdown(user_text)

    with st.chat_message("assistant"):

        st.markdown(_POKA_ASSISTANT_ID, unsafe_allow_html=True)

        typing_box = _show_typing()

        try:

            known_ids = _known_output_ids()

            output: str = run_agent(
                send_text,
                history=prior_history,
                raw_messages=prior_raw,
                image_ids=image_ids,
                force_web_search=force_search,
                project_context=get_active_project_context(),
            )

            typing_box.empty()

            st.markdown(output)

            fresh_metas = _outputs_since(known_ids)
            new_artifacts = [
                {"id": m.id, "kind": m.kind, "name": m.display_name}
                for m in fresh_metas
            ]

            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": output,
                "time": utcnow_iso(),
                **_assistant_meta(force_search),
            }
            if new_artifacts:
                assistant_msg["artifacts"] = new_artifacts
            assistant_sources = _sources_section(assistant_msg)
            if assistant_sources:
                st.markdown(assistant_sources, unsafe_allow_html=True)

            for meta in fresh_metas:
                _render_message_artifact(
                    meta.id, meta.kind, meta.display_name,
                    f"dl-{meta.id}-{len(st.session_state.messages)}",
                )

            st.session_state.messages.append(assistant_msg)

            st.session_state.pop("last_failed", None)

            persist()

            # Settle the finished turn into history above the composer.
            st.rerun()

        except Exception as e:

            typing_box.empty()

            st.session_state.last_failed = send_text

            st.error(f"Request failed: {e}")


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
        # Retry executes with the session's current toggle state (the
        # original one-shot was consumed by the failed send), so record
        # whatever this retry actually used — never the failed attempt's.
        retry_search = bool(st.session_state.get("force_search", False))
        try:
            known_ids = _known_output_ids()
            output: str = run_agent(
                str(send_text),
                history=retry_history,
                raw_messages=retry_raw,
                project_context=get_active_project_context(),
            )
            typing_box.empty()
            st.markdown(output)
            retry_metas = _outputs_since(known_ids)
            retry_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": output,
                "time": utcnow_iso(),
                **_assistant_meta(retry_search),
            }
            if retry_metas:
                retry_msg["artifacts"] = [
                    {"id": m.id, "kind": m.kind, "name": m.display_name}
                    for m in retry_metas
                ]
            retry_sources = _sources_section(retry_msg)
            if retry_sources:
                st.markdown(retry_sources, unsafe_allow_html=True)
            for meta in retry_metas:
                _render_message_artifact(
                    meta.id, meta.kind, meta.display_name,
                    f"dl-{meta.id}-{len(st.session_state.messages)}",
                )
            st.session_state.messages.append(retry_msg)
            persist()
            # Settle the finished turn into history above the composer.
            st.rerun()
        except Exception as e:
            typing_box.empty()
            st.session_state.last_failed = send_text
            st.error(f"Request failed: {e}")
            st.rerun()


def _regenerate_last() -> None:
    """Append a fresh answer to the latest exchange (original kept).

    Rebuilds the request from the persisted user message — raw content
    plus stored attachment links re-expanded through the same hint
    builders as a fresh send — then runs the standard agent path with
    history ending before the previous assistant reply. Never mutates
    or deletes existing messages; on failure the rebuilt request lands
    in last_failed so Retry can recover it. No-ops with a toast unless
    the open conversation ends in user → assistant.
    """
    msgs = list(st.session_state.get("messages", []))
    if (
        len(msgs) < 2
        or not isinstance(msgs[-1], dict)
        or msgs[-1].get("role") != "assistant"
        or not isinstance(msgs[-2], dict)
        or msgs[-2].get("role") != "user"
    ):
        st.toast("Nothing to regenerate.")
        return
    user_msg = msgs[-2]
    prior = msgs[:-1]
    send_text: str = str(user_msg.get("content", "") or "")
    entries = [
        a for a in (user_msg.get("attachments") or [])
        if isinstance(a, dict) and a.get("id")
    ]
    total = len(entries)
    if total > 1:
        send_text += _attachments_overview([
            {
                "name": str(a.get("name", "file")),
                "kind": str(a.get("kind", "image")),
            }
            for a in entries
        ])
    for position, att in enumerate(entries, start=1):
        kind: str = str(att.get("kind", ""))
        upload_id: str = str(att.get("id", ""))
        disp_name: str = str(att.get("name", "file"))
        hint_entry = {"kind": kind, "upload_id": upload_id,
                      "name": disp_name}
        # Same branch shape as a fresh send (pdf/csv hint-only,
        # everything else also attempted as an image); retry parity is
        # intentional — regeneration costs one bounded call either way.
        send_text += _attachment_hint(hint_entry, position, total)
    regen_history = build_chat_history(prior[:-1])
    regen_raw: List[Dict[str, Any]] = [
        dict(m) for m in prior[:-1] if isinstance(m, dict)
    ]
    with st.chat_message("assistant"):
        st.markdown(_POKA_ASSISTANT_ID, unsafe_allow_html=True)
        typing_box = _show_typing()
        # Same one-shot semantics as retry: the consumed intent is gone,
        # so record whatever this run actually used.
        regen_search = bool(st.session_state.get("force_search", False))
        try:
            known_ids = _known_output_ids()
            output: str = run_agent(
                str(send_text),
                history=regen_history,
                raw_messages=regen_raw,
                project_context=get_active_project_context(),
            )
            typing_box.empty()
            st.markdown(output)
            regen_metas = _outputs_since(known_ids)
            regen_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": output,
                "time": utcnow_iso(),
                **_assistant_meta(regen_search),
            }
            if regen_metas:
                regen_msg["artifacts"] = [
                    {"id": m.id, "kind": m.kind, "name": m.display_name}
                    for m in regen_metas
                ]
            regen_sources = _sources_section(regen_msg)
            if regen_sources:
                st.markdown(regen_sources, unsafe_allow_html=True)
            for meta in regen_metas:
                _render_message_artifact(
                    meta.id, meta.kind, meta.display_name,
                    f"dl-{meta.id}-{len(st.session_state.messages)}",
                )
            st.session_state.messages.append(regen_msg)
            persist()
            # Settle the finished turn into history above the composer.
            st.rerun()
        except Exception as e:
            typing_box.empty()
            st.session_state.last_failed = send_text
            st.error(f"Request failed: {e}")
            st.rerun()
