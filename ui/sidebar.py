"""Sidebar: brand, model status, mode, chats, memory, files, stats.

Page section only: persistence and stores come from
application.session, memory facts from services.memory. Returns the
active model name for the page footer.
"""

import html
from typing import Any, Dict

import streamlit as st

from application.session import (
    _file_store,
    _pending_list,
    _user_store,
    archive_current_chat,
    ensure_current_chat_id,
    persist,
)
from services.context import get_current_user_id
from application import workflows as workflow_svc
from services.memory import (
    delete_memory_fact,
    list_memory_facts,
    load_structured_memory,
)
from services import research as research_svc
from services.limits import (
    MAX_CHAT_TITLE_CHARS,
    MAX_DISPLAY_NAME_CHARS,
    MAX_ERROR_SNIPPET_CHARS,
    UI_TEXT_AREA_HEIGHT,
)
from services.storage import StorageError, clean_source_record
from services.timeutil import utcnow_iso, utcnow_stamp
from ui.components import (
    _artifact_card_html,
    _artifact_sub_for,
    _export_chat_to_markdown,
    _format_bytes,
    _rel_date,
    mem_date_label,
    mem_source_label,
    mem_type_label,
)
from ui.uploads import _kind_icon


# --- New theme project cards (ui/theme/components.py + layout.py) ---
# Pure HTML builders; Streamlit buttons below keep behavior/keys unchanged.


def _section_title_html(text: str) -> str:
    """Section header using the new theme class."""
    return f'<p class="sidebar-section-title">{html.escape(str(text))}</p>'


def _project_card_html(name: str, meta: str, active: bool) -> str:
    """Project row card with icon, title, meta; active gets .active."""
    raw_name = str(name or "Untitled")
    safe_name = html.escape(raw_name)
    safe_meta = html.escape(str(meta or ""))
    first = html.escape(raw_name.strip()[:1] or "P")
    cls = "project-card active" if active else "project-card"
    return (
        f'<div class="{cls}">'
        f'<div class="project-card-icon" aria-hidden="true">{first}</div>'
        '<div class="project-card-info">'
        f'<div class="project-card-title">{safe_name}</div>'
        f'<div class="project-card-meta">{safe_meta}</div>'
        "</div></div>"
    )


def _new_project_btn_html() -> str:
    """New Project primary button wrapper (visual; behavior is Streamlit)."""
    return '<div class="btn-primary">New Project</div>'


def _artifact_sub(meta: Any) -> str:
    """One-line kind/size/date summary from a live registry record."""
    return _artifact_sub_for(
        getattr(meta, "kind", ""), getattr(meta, "display_name", ""),
        getattr(meta, "size", None), getattr(meta, "created", None),
    )


def _upload_kind_label(kind: Any) -> str:
    """Human label for a staged-upload kind (never invented)."""
    if kind == "pdf":
        return "PDF"
    if kind == "csv":
        return "CSV"
    return "Image"


def _upload_sub(meta: Any) -> str:
    """One-line kind/size/date summary from a live upload record."""
    bits = [_upload_kind_label(getattr(meta, "kind", ""))]
    size = _format_bytes(getattr(meta, "size", None))
    if size:
        bits.append(size)
    when = _rel_date(getattr(meta, "created", None))
    if when:
        bits.append(when)
    return " · ".join(b for b in bits if b)


def _upload_row_html(meta: Any) -> str:
    """Upload row markup from a live registry record (visual only)."""
    return (
        '<div class="poka-file-row">'
        '<span class="poka-file-icon" aria-hidden="true">'
        + _kind_icon(str(getattr(meta, "kind", "")))
        + "</span>"
        '<span class="poka-file-name" title="'
        + html.escape(str(getattr(meta, "display_name", "")), quote=True)
        + '">'
        + html.escape(str(getattr(meta, "display_name", "")))
        + "</span>"
        "</div>"
        f'<p class="poka-file-sub">{html.escape(_upload_sub(meta))}</p>'
    )


def _vault_rows() -> list:
    """Remembered facts for display: [(key, delete_ref, fact)].

    key is unique per row (fact index, or "name" for the synthetic
    orphaned-user_name row); delete_ref is what delete_memory_fact
    receives (index for stored facts, value for the synthetic row).

    Reads only the current user's vault; any failure renders as empty
    (chat must never break on memory trouble). A stored user_name with
    no matching name fact is surfaced as a synthetic row so orphaned
    names stay visible and removable.
    """
    try:
        facts = list_memory_facts()
    except Exception:
        return []
    if not isinstance(facts, list):
        return []
    rows: list = []
    try:
        user_name = load_structured_memory().get("user_name")
    except Exception:
        user_name = None
    if isinstance(user_name, str) and user_name.strip():
        clean_name = user_name.strip()
        if not any(
            isinstance(f, dict)
            and f.get("type") == "name"
            and str(f.get("value", "")).strip().lower() == clean_name.lower()
            for f in facts
        ):
            rows.append(("name", clean_name,
                         {"type": "name", "value": clean_name}))
    for idx, fact in enumerate(facts):
        if isinstance(fact, dict):
            rows.append((idx, idx, fact))
    return rows


def _mem_row_html(fact: dict) -> str:
    """Compact vault row (visual only; values are escaped)."""
    value = fact.get("value", "")
    if not isinstance(value, str) or not value.strip():
        value = "(empty memory)"
    parts = [
        '<div class="poka-mem-row">',
        '<div class="poka-mem-head">'
        f'<span class="poka-mem-type">{html.escape(mem_type_label(fact))}</span>',
    ]
    source = mem_source_label(fact)
    if source:
        parts.append(f'<span class="poka-mem-src">{html.escape(source)}</span>')
    parts.append("</div>")
    parts.append(f'<div class="poka-mem-val">{html.escape(value.strip())}</div>')
    when = mem_date_label(fact.get("date", ""))
    if when:
        parts.append(f'<div class="poka-mem-date">{html.escape(when)}</div>')
    parts.append("</div>")
    return "".join(parts)


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


def get_active_project() -> Any:
    """Re-resolved active project record, or None for Personal.

    Reads session active_project_id and resolves it against the
    caller's own registry on every call: missing, malformed,
    foreign, or archived ids safely fall back to Personal. Shared by
    the sidebar and the main-area context indicator.
    """
    try:
        active_id = st.session_state.get("active_project_id", None)
    except Exception:
        return None
    if not isinstance(active_id, str) or not active_id:
        return None
    try:
        candidate = _user_store().get_project(active_id)
    except StorageError:
        return None
    if isinstance(candidate, dict) and not candidate.get("archived", False):
        return candidate
    return None


from ui.project_resources import (
    MAX_PROJECT_SOURCES,
    artifact_entries_in,
    member_conversations,
    messages_of,
    open_bucket,
    project_bucket,
    source_entries_in,
    upload_ids_in,
)


def _md_text(text: Any) -> str:
    """Escape user content for markdown-rendered widgets.

    html.escape handles HTML; backslash-escaping brackets additionally
    keeps [...](...) text from becoming links in captions/toasts.
    """
    return html.escape(str(text or "")).replace("[", "\\[")


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

        # ---- Active model (resolved here, displayed in Account below) ----
        model_name: str = _active_model_name()
        model_live: bool = _model_is_live(model_name)
        dot_class: str = "poka-dot-online" if model_live else "poka-dot-offline"

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
            if match_count == 0:
                st.markdown(
                    '<p class="poka-match">No matches — try different words</p>',
                    unsafe_allow_html=True,
                )
            else:
                noun: str = "match" if match_count == 1 else "matches"
                st.markdown(
                    f'<p class="poka-match">{match_count} {noun}</p>',
                    unsafe_allow_html=True,
                )

        # ---- Projects (UI context only: selection for later phases.
        # No conversation/file filtering happens here yet.) ----
        # NEW theme header (old kept active for compat).
        st.markdown('<p class="section-label">Projects</p>', unsafe_allow_html=True)
        st.markdown(_section_title_html("Projects"), unsafe_allow_html=True)

        try:
            _project_list = _user_store().list_projects()
        except StorageError:
            _project_list = []

        # Re-resolved every render (helper); stale, foreign, or archived
        # ids fall back to Personal. Never trust a cached name.
        _active_project = get_active_project()
        _valid_project_ids = {
            str(p.get("id", ""))
            for p in _project_list
            if isinstance(p, dict) and str(p.get("id", ""))
        }

        # NEW theme New Project primary button (visual wrapper + primary action).
        st.markdown(_new_project_btn_html(), unsafe_allow_html=True)
        if st.button(
            "New Project",
            key="project-create-new",
            help="Create project",
            type="primary",
        ):
            st.session_state.creating_project = True
            st.rerun()

        _personal_col, _create_col = st.columns([4, 1])
        with _personal_col:
            if st.button(
                "Personal",
                key="project-personal",
                help="Personal workspace",
                disabled=_active_project is None,
            ):
                st.session_state.active_project_id = None
                st.session_state.renaming_idx = None
                st.rerun()
        with _create_col:
            # NEW: same key/label, primary type for .btn-primary language.
            if st.button(
                "+",
                key="project-create",
                help="Create project",
                type="primary",
            ):
                st.session_state.creating_project = True
                st.rerun()

        if st.session_state.get("creating_project", False):
            _new_name: str = st.text_input(
                "Project name",
                placeholder="Project name",
                label_visibility="collapsed",
                max_chars=60,
                key="project-name-box",
            )
            _csave_col, _ccancel_col = st.columns(2)
            if _csave_col.button("Save", key="project-create-save"):
                try:
                    _created = _user_store().create_project(_new_name)
                except ValueError:
                    st.toast("Enter a project name.")
                except StorageError:
                    st.toast("Could not create project.")
                else:
                    st.session_state.active_project_id = _created["id"]
                    st.session_state.creating_project = False
                    st.toast("Project created.")
                    st.rerun()
            if _ccancel_col.button("Cancel", key="project-create-cancel"):
                st.session_state.creating_project = False
                st.rerun()

        for _project in _project_list:
            if not isinstance(_project, dict):
                continue
            _pid: str = str(_project.get("id", ""))
            if not _pid:
                continue
            _pfull: str = str(_project.get("name", "")).strip()[:60] or "Untitled"
            _pname: str = _pfull[:34] or "Untitled"
            _is_active: bool = (
                _active_project is not None
                and _active_project.get("id") == _pid
            )
            # NEW theme project card (visual; buttons below keep behavior).
            # Meta uses the real created date (no invented member counts).
            _pmeta: str = _rel_date(_project.get("created")) or "Project"
            st.markdown(
                _project_card_html(_pname, _pmeta, _is_active),
                unsafe_allow_html=True,
            )
            _prow_col, _ppencil_col = st.columns([4, 1])
            with _prow_col:
                if st.button(
                    _pname,
                    key=f"project-{_pid}",
                    help="Open project",
                    disabled=_is_active,
                ):
                    try:
                        _selected = _user_store().get_project(_pid)
                    except StorageError:
                        _selected = None
                    if isinstance(_selected, dict) and not _selected.get(
                            "archived", False):
                        st.session_state.active_project_id = _selected["id"]
                    else:
                        st.session_state.active_project_id = None
                        st.toast("Project unavailable.")
                    st.session_state.renaming_idx = None
                    st.rerun()
            with _ppencil_col:
                if st.button(
                    "⋯",
                    key=f"project-pencil-{_pid}",
                    help="Rename or archive project",
                ):
                    st.session_state.renaming_project = _pid
                    st.rerun()

            if st.session_state.get("renaming_project") == _pid:
                _edit_name: str = st.text_input(
                    "Rename project",
                    value=_pfull,
                    label_visibility="collapsed",
                    max_chars=60,
                    key=f"project-rename-box-{_pid}",
                )
                _rsave_col, _rcancel_col = st.columns(2)
                if _rsave_col.button("Save", key=f"project-rename-save-{_pid}"):
                    try:
                        _renamed = _user_store().rename_project(_pid, _edit_name)
                    except ValueError:
                        st.toast("Enter a project name.")
                    except StorageError:
                        st.toast("Could not rename project.")
                    else:
                        if _renamed:
                            st.toast("Project renamed.")
                        else:
                            st.toast("Project unavailable.")
                        st.session_state.renaming_project = None
                        st.rerun()
                if _rcancel_col.button("Cancel", key=f"project-rename-cancel-{_pid}"):
                    st.session_state.renaming_project = None
                    st.rerun()
                if st.button("Archive project", key=f"project-archive-{_pid}"):
                    st.session_state.confirm_archive_project = _pid
                    st.rerun()
                if st.session_state.get("confirm_archive_project") == _pid:
                    st.caption(
                        f"Archive '{_md_text(_pname)}'? It will leave the list, "
                        "nothing is deleted."
                    )
                    _yes_col, _no_col = st.columns(2)
                    if _yes_col.button("Yes", key="project-archive-confirm"):
                        try:
                            _archived_ok = _user_store().archive_project(_pid)
                        except StorageError:
                            _archived_ok = False
                        if _archived_ok and st.session_state.get(
                                "active_project_id") == _pid:
                            st.session_state.active_project_id = None
                        st.session_state.confirm_archive_project = None
                        st.session_state.renaming_project = None
                        if _archived_ok:
                            st.toast("Project archived.")
                        else:
                            st.toast("Project unavailable.")
                        st.rerun()
                    if _no_col.button("Cancel", key="project-archive-dismiss"):
                        st.session_state.confirm_archive_project = None
                        st.rerun()

        # ---- Project context (active project only; Personal shows
        # nothing). Read fresh every render; never cached in session.
        if isinstance(_active_project, dict):
            _ctx_pid: str = str(_active_project.get("id", ""))
            try:
                _ctx_current = _user_store().load_project_context(_ctx_pid)
            except StorageError:
                _ctx_current = ""
            st.markdown(
                '<p class="poka-card-sub">Context</p>',
                unsafe_allow_html=True,
            )
            if not _ctx_current:
                st.caption(
                    "No project context yet. Add a short description of "
                    "this project, its goals, or conventions to help "
                    "Poka work more effectively here."
                )
            else:
                st.caption(
                    "Used to help Poka understand this project. "
                    "Only applies inside this project."
                )
            _ctx_text: str = st.text_area(
                "Project context",
                value=_ctx_current,
                height=UI_TEXT_AREA_HEIGHT,
                placeholder="e.g. FastAPI backend, prefers type hints…",
                label_visibility="collapsed",
                key="project-context-box",
            )
            if st.button("Save context", key="project-context-save"):
                try:
                    _user_store().save_project_context(_ctx_pid, _ctx_text)
                except ValueError as e:
                    st.toast(str(e))
                except StorageError as e:
                    st.toast(f"Could not save context: {e}")
                else:
                    st.toast("Project context saved.")
                    st.rerun()

        # ---- Recents: filtered by the active project bucket.
        # Presentation-only: the archive list is never mutated here, and
        # keys/operations use true list indexes, never filter positions.
        st.markdown(
            '<p class="section-label">Recents</p>',
            unsafe_allow_html=True,
        )
        st.markdown(_section_title_html("Recents"), unsafe_allow_html=True)

        _active_bucket = (
            _active_project.get("id")
            if isinstance(_active_project, dict) else None
        )
        _visible_chats = [
            (i, chat)
            for i, chat in enumerate(list(st.session_state.chats))
            if project_bucket(chat, _valid_project_ids) == _active_bucket
        ]

        if _visible_chats:

            for i, chat in _visible_chats:

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
                        st.session_state.current_chat_id = selected.get("id")
                        st.session_state.current_project_id = selected.get(
                            "project_id")
                        # The opened conversation is authoritative for its
                        # own membership: sync the visible project context.
                        _adopted_pid = selected.get("project_id")
                        if (isinstance(_adopted_pid, str) and _adopted_pid
                                and _adopted_pid in _valid_project_ids):
                            st.session_state.active_project_id = _adopted_pid
                        else:
                            st.session_state.active_project_id = None

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
                            new_title.strip()[:MAX_CHAT_TITLE_CHARS] or chat_title
                        )
                        st.session_state.renaming_idx = None
                        persist()
                        st.rerun()
                    if cancel_col.button("Cancel", key=f"rename-cancel-{i}"):
                        st.session_state.renaming_idx = None
                        st.rerun()

        else:
            if st.session_state.chats:
                # Conversations exist, but none belong to this bucket.
                if isinstance(_active_project, dict):
                    st.markdown(
                        '<p class="poka-empty">No conversations in '
                        f"'{html.escape(str(_active_project.get('name', '')))}' "
                        "yet. New chats started here will belong to it.</p>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<p class="poka-empty">No personal conversations '
                        "yet. Start a new chat above.</p>",
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown(
                    '<p class="poka-empty">No recent conversations yet — '
                    "start a new chat above</p>",
                    unsafe_allow_html=True,
                )

        # ---- Conversation: explicit move for the open chat only.
        # Assignment never happens implicitly (project-row clicks only
        # switch context). Shown only while a conversation is open.
        # Conversation actions appear only when a move target can exist:
        # an open conversation plus at least one project (or a conversation
        # already carrying a project). Otherwise the control is noise.
        _conv_pid = st.session_state.get("current_project_id", None)
        _move_targets = bool(_project_list) or (
            isinstance(_conv_pid, str) and bool(_conv_pid))
        if st.session_state.get("messages", []) and _move_targets:
            st.markdown(
                '<p class="section-label">Conversation</p>',
                unsafe_allow_html=True,
            )
            _current_pid = st.session_state.get("current_project_id", None)
            _current_name = None
            if isinstance(_current_pid, str) and _current_pid:
                try:
                    _current_rec = _user_store().get_project(_current_pid)
                except StorageError:
                    _current_rec = None
                if isinstance(_current_rec, dict) and not _current_rec.get(
                        "archived", False):
                    _current_name = str(_current_rec.get("name", ""))
            if _current_name:
                st.caption(f"In {_md_text(_current_name)}.")
            else:
                st.caption("In Personal.")
            if st.button(
                "Move to project",
                key="conv-move-open",
                help="Move this conversation to a project",
            ):
                st.session_state.moving_conversation = True
                st.rerun()

            if st.session_state.get("moving_conversation", False):
                if st.button(
                    "Personal",
                    key="conv-move-personal",
                    help="Move this conversation to Personal",
                ):
                    ensure_current_chat_id()
                    st.session_state.current_project_id = None
                    st.session_state.moving_conversation = False
                    st.toast("Moved to Personal.")
                    st.rerun()
                for _target in _project_list:
                    if not isinstance(_target, dict):
                        continue
                    _tid: str = str(_target.get("id", ""))
                    if not _tid:
                        continue
                    _tname: str = str(
                        _target.get("name", "")).strip()[:60] or "Untitled"
                    _already = (
                        isinstance(_current_pid, str)
                        and _current_pid == _tid
                    )
                    if st.button(
                        ("✓ " if _already else "") + _tname,
                        key=f"conv-move-{_tid}",
                        help=f"Move this conversation to {_md_text(_tname)}",
                    ):
                        if _already:
                            st.toast("Already here.")
                            st.session_state.moving_conversation = False
                            st.rerun()
                        try:
                            _dest = _user_store().get_project(_tid)
                        except StorageError:
                            _dest = None
                        if isinstance(_dest, dict) and not _dest.get(
                                "archived", False):
                            ensure_current_chat_id()
                            st.session_state.current_project_id = _dest["id"]
                            st.session_state.moving_conversation = False
                            st.toast(f"Moved to {_md_text(_tname)}.")
                        else:
                            st.toast("Project unavailable.")
                        st.rerun()
                if st.button("Cancel", key="conv-move-cancel"):
                    st.session_state.moving_conversation = False
                    st.rerun()

        st.markdown('<div class="poka-divider"></div>', unsafe_allow_html=True)

        # ---- Navigation state for workspace destinations (7F).
        # Minimal view id only; destination bodies render in the main
        # content area. Nothing project- or user-scoped is cached here.
        try:
            _sidebar_view = st.session_state.get("sidebar_view", None)
        except Exception:
            _sidebar_view = None
        if _sidebar_view not in WORKSPACE_VIEWS:
            _sidebar_view = None

        def _toggle_sidebar_view(name: str) -> None:
            try:
                current = st.session_state.get("sidebar_view", None)
            except Exception:
                current = None
            try:
                st.session_state.sidebar_view = None if current == name else name
            except Exception:
                pass

        # ---- Workspace navigation (7F navigation-first).
        # Destinations render in the main content area; this sidebar
        # keeps only compact navigation rows.
        st.markdown('<p class="section-label">Workspace</p>', unsafe_allow_html=True)
        if st.button(
            "Research",
            key="nav-research",
            help="Open the Research workspace",
            disabled=_sidebar_view == "research",
        ):
            try:
                st.session_state.sidebar_view = (
                    None if st.session_state.get("sidebar_view", None) == "research"
                    else "research")
                st.session_state.more_open = False
            except Exception:
                pass
            st.rerun()
        if st.button(
            "Workflows",
            key="nav-workflows",
            help="Open guided workflows",
            disabled=_sidebar_view == "workflows",
        ):
            try:
                st.session_state.sidebar_view = (
                    None if st.session_state.get("sidebar_view", None) == "workflows"
                    else "workflows")
                st.session_state.more_open = False
            except Exception:
                pass
            st.rerun()

        # ---- More: secondary navigation, closed by default (7G).
        # Only the toggle is permanently visible; destination rows
        # appear on demand and open the main workspace. Selecting a
        # destination closes More again. Keys and behavior unchanged.
        st.markdown('<p class="section-label">More</p>', unsafe_allow_html=True)
        try:
            _more_open = bool(st.session_state.get("more_open", False))
        except Exception:
            _more_open = False
        if st.button(
            "More ▾" if _more_open else "More ▸",
            key="more-toggle",
            help="Show secondary destinations",
        ):
            try:
                st.session_state.more_open = not bool(
                    st.session_state.get("more_open", False))
            except Exception:
                pass
            st.rerun()
        if _more_open:
            for _nav_key, _nav_label, _nav_tip in (
                ("nav-memory", "Memory", "Saved notes and remembered facts"),
                ("nav-files", "Files", "Uploaded files"),
                ("nav-artifacts", "Artifacts", "Generated documents and decks"),
                ("nav-sources", "Sources", "Cited web sources"),
                ("nav-stats", "Stats", "Usage overview"),
            ):
                if st.button(
                    _nav_label,
                    key=_nav_key,
                    help=_nav_tip,
                    disabled=_sidebar_view == _nav_key[4:],
                ):
                    _toggle_sidebar_view(_nav_key[4:])
                    try:
                        st.session_state.more_open = False
                    except Exception:
                        pass
                    st.rerun()

        # ---- (Memory renders in the main workspace when selected.) ----

        # ---- (Files/Artifacts/Sources render in the main workspace;
        # scope derivation lives in _workspace_scope_bundle.) ----

        # ---- (Artifacts gallery renders in the main workspace.) ----

        # ---- (Sources render in the main workspace when selected.) ----

        # ---- (Research renders in the main workspace when selected.) ----

        # ---- (Stats renders in the main workspace when selected.) ----

        # ---- Account: stable bottom anchor (model + chat export + cleanup).
        # Keys and behavior unchanged; only placement moved here.
        st.markdown('<div class="poka-divider"></div>', unsafe_allow_html=True)
        st.markdown(
            '<p class="section-label">Account</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="poka-model">'
            f'<span class="poka-dot {dot_class}" aria-hidden="true"></span>'
            f'<span class="poka-model-name">{html.escape(model_name)}</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        try:
            _account_uid = str(get_current_user_id() or "").strip()[:24]
        except Exception:
            _account_uid = ""
        if _account_uid:
            st.caption(f"Signed in as {_md_text(_account_uid)}.")
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


# ============================================================
# Main-workspace views (7F navigation-first).
# Each renders one destination's EXISTING body in the MAIN content
# area when sidebar_view selects it. All widget keys, logic,
# ownership checks, storage paths, and ordering are unchanged —
# only the render location moved out of the sidebar.
# ============================================================

#: Sidebar destinations that render as main-workspace views.
WORKSPACE_VIEWS = ("research", "workflows", "memory", "files",
                   "artifacts", "sources", "stats")


def get_sidebar_view() -> Any:
    """Return the selected workspace view id, or None (fail closed)."""
    try:
        value = st.session_state.get("sidebar_view", None)
    except Exception:
        return None
    return value if isinstance(value, str) and value in WORKSPACE_VIEWS else None


def _clear_sidebar_view() -> None:
    """Return to chat; preserves conversation/projects/attachments."""
    try:
        st.session_state.sidebar_view = None
    except Exception:
        pass


def _workspace_back_row() -> None:
    """Shared 'Back to chat' row; clears view only (never chat state)."""
    if st.button("Back to chat", key="back-to-chat",
                 help="Return to the conversation; everything is kept"):
        _clear_sidebar_view()
        st.rerun()


def _workspace_scope_bundle() -> Dict[str, Any]:
    """Re-resolve project scope for workspace views (never cached).

    Mirrors the former sidebar derivation: Personal keeps full
    registries; an active project derives Files/Artifacts/Sources from
    member conversations plus the open conversation in the same bucket.
    """
    try:
        _projects = _user_store().list_projects()
    except StorageError:
        _projects = []
    try:
        _active = get_active_project()
    except Exception:
        _active = None
    _valid_ids = {
        str(p.get("id", ""))
        for p in _projects
        if isinstance(p, dict) and str(p.get("id", ""))
    }
    _bucket = _active.get("id") if isinstance(_active, dict) else None
    _messages: list = []
    try:
        _open_messages = [m for m in st.session_state.get("messages", [])
                          if isinstance(m, dict)]
        _archived = list(st.session_state.get("chats", []))
    except Exception:
        _open_messages, _archived = [], []
    if _bucket is not None:
        if open_bucket(st.session_state.get("current_project_id", None),
                       _valid_ids) == _bucket:
            _messages.extend(_open_messages)
        for _convo in member_conversations(_archived, _bucket, _valid_ids):
            _messages.extend(messages_of([_convo]))
    else:
        if open_bucket(st.session_state.get("current_project_id", None),
                       _valid_ids) is None:
            _messages.extend(_open_messages)
        for _convo in member_conversations(_archived, None, _valid_ids):
            _messages.extend(messages_of([_convo]))
    return {
        "projects": _projects,
        "active": _active,
        "valid_ids": _valid_ids,
        "scope_id": _bucket,
        "upload_ids": upload_ids_in(_messages),
        "artifacts": artifact_entries_in(_messages),
        "sources": source_entries_in(_messages),
    }


def render_artifacts_view() -> None:
    """Main-workspace Artifacts gallery (moved from sidebar).

    Newest first, download + validated Regenerate, legacy
    download-only, project/personal scope. Keys and logic unchanged.
    """
    st.markdown('<p class="section-label">Artifacts</p>', unsafe_allow_html=True)
    _bundle = _workspace_scope_bundle()
    _scope_id = _bundle["scope_id"]
    _scope_artifacts = _bundle["artifacts"]
    _valid_project_ids = _bundle["valid_ids"]
    if _scope_id is None:
        # Personal: full registry, newest first (includes legacy
        # outputs without message linkage). Chronological only:
        # no parent IDs exist, so no version grouping is
        # fabricated — regeneration simply appends a new file.
        try:
            owned_outputs = research_svc.sort_artifacts_newest_first(
                _file_store().list_outputs())
        except StorageError:
            owned_outputs = []
        if owned_outputs:
            st.caption(
                "Newest first · Regeneration creates a new file; "
                "originals are kept.")
            for meta in owned_outputs[:8]:
                st.markdown(
                    _artifact_card_html(
                        str(meta.display_name),
                        str(meta.kind),
                        _artifact_sub(meta),
                    ),
                    unsafe_allow_html=True,
                )
                file_bytes = None
                try:
                    file_bytes = _file_store().read_output(meta.id)
                except StorageError:
                    file_bytes = None
                if file_bytes is not None:
                    _suffix = str(meta.display_name).rsplit(".", 1)
                    _dl_label = (
                        f"Download {_suffix[-1].upper()}"
                        if len(_suffix) == 2 and _suffix[-1]
                        else "Download file"
                    )
                    st.download_button(
                        _dl_label,
                        file_bytes,
                        file_name=meta.display_name,
                        key=f"side-dl-{meta.id}",
                    )
                try:
                    _can_regen = research_svc.can_regenerate(
                        _file_store(), meta.id)
                except Exception:
                    _can_regen = False
                if _can_regen:
                    if st.button(
                        "Regenerate",
                        key=f"regen-side-{meta.id}",
                        help="Creates a new artifact using the saved "
                        "generation settings.",
                    ):
                        try:
                            _new_meta = research_svc.regenerate_artifact(
                                _file_store(), meta.id)
                        except ValueError as e:
                            st.toast(str(e)[:MAX_ERROR_SNIPPET_CHARS])
                        except RuntimeError as e:
                            st.toast(str(e)[:MAX_ERROR_SNIPPET_CHARS])
                        except Exception:
                            st.toast("Could not regenerate this file.")
                        else:
                            try:
                                _msgs = st.session_state.get(
                                    "messages", [])
                                _cur_pid = st.session_state.get(
                                    "current_project_id", None)
                                from ui.project_resources import open_bucket as _open_bucket
                                # Personal scope: link when the open
                                # conversation is also Personal.
                                if (isinstance(_msgs, list) and _msgs
                                        and _open_bucket(
                                            _cur_pid,
                                            _valid_project_ids) is None):
                                    _msgs.append({
                                        "role": "assistant",
                                        "content": "Regenerated file: "
                                        f"{_new_meta.display_name}",
                                        "time": utcnow_iso(),
                                        "artifacts": [{
                                            "id": _new_meta.id,
                                            "kind": _new_meta.kind,
                                            "name": _new_meta.display_name,
                                        }],
                                    })
                                    st.session_state.messages = _msgs
                                    persist()
                            except Exception:
                                pass
                            st.toast("Regenerated as a new file.")
                            st.rerun()
            if len(owned_outputs) > 8:
                st.caption(
                    f"Showing 8 of {len(owned_outputs)} artifacts."
                )
        else:
            st.markdown(
                '<p class="poka-empty">No generated files yet. '
                "When Poka creates a document or presentation, "
                "it will appear here.</p>",
                unsafe_allow_html=True,
            )
    else:
        # Project: derived view, newest first; legacy unlinked
        # outputs stay out. Missing records render expired.
        # Chronological only — no version grouping is fabricated
        # (no parent IDs; filename similarity is never lineage).
        if _scope_artifacts:
            try:
                _resolved_pairs: list = []
                for _e in _scope_artifacts:
                    try:
                        _m = _file_store().get_output(_e["id"])
                    except StorageError:
                        _m = None
                    _resolved_pairs.append((_e, _m))
                _valid_pairs = [p for p in _resolved_pairs if p[1] is not None]
                _expired_pairs = [p for p in _resolved_pairs if p[1] is None]
                _valid_pairs = sorted(
                    _valid_pairs,
                    key=lambda p: float(getattr(p[1], "created", 0.0) or 0.0),
                    reverse=True)
                _ordered_pairs = _valid_pairs + _expired_pairs
            except Exception:
                _ordered_pairs = [(_e, None) for _e in _scope_artifacts]
            st.caption(
                "Newest first · Regeneration creates a new file; "
                "originals are kept.")
            _shown_pairs = _ordered_pairs[:8]
            for _entry, _pre_resolved in _shown_pairs:
                _ameta = _pre_resolved
                if _ameta is None:
                    try:
                        _ameta = _file_store().get_output(_entry["id"])
                    except StorageError:
                        _ameta = None
                if _ameta is None:
                    st.markdown(
                        _artifact_card_html(
                            _entry["name"], _entry["kind"], "Expired",
                            expired=True,
                        ),
                        unsafe_allow_html=True,
                    )
                    continue
                st.markdown(
                    _artifact_card_html(
                        str(_ameta.display_name),
                        str(_ameta.kind),
                        _artifact_sub(_ameta),
                    ),
                    unsafe_allow_html=True,
                )
                _artifact_bytes = None
                try:
                    _artifact_bytes = _file_store().read_output(
                        _ameta.id)
                except StorageError:
                    _artifact_bytes = None
                if _artifact_bytes is not None:
                    _asuffix = str(
                        _ameta.display_name).rsplit(".", 1)
                    _alabel = (
                        f"Download {_asuffix[-1].upper()}"
                        if len(_asuffix) == 2 and _asuffix[-1]
                        else "Download file"
                    )
                    st.download_button(
                        _alabel,
                        _artifact_bytes,
                        file_name=_ameta.display_name,
                        key=f"side-dl-{_ameta.id}",
                    )
                try:
                    _can_regen_p = research_svc.can_regenerate(
                        _file_store(), _ameta.id)
                except Exception:
                    _can_regen_p = False
                if _can_regen_p:
                    if st.button(
                        "Regenerate",
                        key=f"regen-side-{_ameta.id}",
                        help="Creates a new artifact using the saved "
                        "generation settings.",
                    ):
                        try:
                            _new_meta_p = research_svc.regenerate_artifact(
                                _file_store(), _ameta.id)
                        except ValueError as e:
                            st.toast(str(e)[:MAX_ERROR_SNIPPET_CHARS])
                        except RuntimeError as e:
                            st.toast(str(e)[:MAX_ERROR_SNIPPET_CHARS])
                        except Exception:
                            st.toast("Could not regenerate this file.")
                        else:
                            try:
                                _msgs_p = st.session_state.get(
                                    "messages", [])
                                _cur_pid_p = st.session_state.get(
                                    "current_project_id", None)
                                from ui.project_resources import open_bucket as _open_bucket_p
                                if (isinstance(_msgs_p, list) and _msgs_p
                                        and _open_bucket_p(
                                            _cur_pid_p,
                                            _valid_project_ids) == _scope_id):
                                    _msgs_p.append({
                                        "role": "assistant",
                                        "content": "Regenerated file: "
                                        f"{_new_meta_p.display_name}",
                                        "time": utcnow_iso(),
                                        "artifacts": [{
                                            "id": _new_meta_p.id,
                                            "kind": _new_meta_p.kind,
                                            "name": _new_meta_p.display_name,
                                        }],
                                    })
                                    st.session_state.messages = _msgs_p
                                    persist()
                            except Exception:
                                pass
                            st.toast("Regenerated as a new file.")
                            st.rerun()
            if len(_scope_artifacts) > 8:
                st.caption(
                    f"Showing 8 of {len(_scope_artifacts)} artifacts."
                )
        else:
            st.markdown(
                '<p class="poka-empty">No generated files in this '
                "project yet. Documents Poka creates in this "
                "project's conversations will appear here.</p>",
                unsafe_allow_html=True,
            )
    _workspace_back_row()


def render_sources_view() -> None:
    """Main-workspace Sources view (moved from sidebar).

    Structured provenance only — never parsed, fetched, or refreshed.
    """
    st.markdown('<p class="section-label">Sources</p>', unsafe_allow_html=True)
    _bundle = _workspace_scope_bundle()
    _scope_id = _bundle["scope_id"]
    _scope_sources = _bundle["sources"]
    _shown_sources = _scope_sources[:MAX_PROJECT_SOURCES]
    if _shown_sources:
        for _n, _rec in enumerate(_shown_sources, start=1):
            _href = str(_rec.get("url", "")).replace(")", "%29")
            st.markdown(
                '<p class="poka-source">'
                f'<span class="poka-source-n">[{_n}]</span> '
                f'<a href="{html.escape(_href, quote=True)}" '
                'target="_blank" rel="noopener noreferrer">'
                f"{html.escape(str(_rec.get('title', '')))}</a> "
                '<span class="poka-source-d">'
                f"{html.escape(str(_rec.get('domain', '')))}</span>"
                "</p>",
                unsafe_allow_html=True,
            )
        if len(_scope_sources) > MAX_PROJECT_SOURCES:
            st.caption(
                f"Showing {MAX_PROJECT_SOURCES} of "
                f"{len(_scope_sources)} sources."
            )
    else:
        if _scope_id is None:
            st.markdown(
                '<p class="poka-empty">No web sources yet. Answers '
                "with cited web research will list their sources "
                "here.</p>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<p class="poka-empty">No web sources in this '
                "project yet. Cited research from this project's "
                "conversations will appear here.</p>",
                unsafe_allow_html=True,
            )
    _workspace_back_row()


def render_research_view() -> None:
    """Main-workspace Research view (moved from sidebar).

    Newest-first list + scoped viewer + Generate document. Keys,
    ownership, scoping, and validation unchanged.
    """
    st.markdown('<p class="section-label">Research</p>', unsafe_allow_html=True)
    _bundle = _workspace_scope_bundle()
    _active_project = _bundle["active"]
    _valid_project_ids = _bundle["valid_ids"]
    try:
        _active_pid_for_briefs = (
            _active_project.get("id")
            if isinstance(_active_project, dict) else None
        )
    except Exception:
        _active_pid_for_briefs = None
    try:
        _active_pname_for_briefs = (
            str(_active_project.get("name", "")).strip()[:60]
            if isinstance(_active_project, dict) else "")
    except Exception:
        _active_pname_for_briefs = ""
    try:
        _visible_briefs = research_svc.visible_briefs_for_scope(
            _user_store(), _active_pid_for_briefs,
            research_svc.MAX_VISIBLE_BRIEFS)
    except Exception:
        _visible_briefs = []
    try:
        _selected_brief_id = st.session_state.get(
            "selected_brief_id", None)
    except Exception:
        _selected_brief_id = None
    if not _visible_briefs:
        st.markdown(
            '<p class="poka-empty">No saved research briefs yet.</p>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Saved briefs let you return to research later and "
            "generate a document. Ask with web search, then choose "
            "Save as brief.")
    else:
        for _brief in _visible_briefs[:research_svc.MAX_VISIBLE_BRIEFS]:
            if not isinstance(_brief, dict):
                continue
            _bid = str(_brief.get("id", ""))
            if not _bid:
                continue
            _btitle = research_svc.brief_display_title(_brief, 60)
            _blabel = _btitle[:34] or "Untitled"
            _is_sel = research_svc.is_selected_brief(
                _selected_brief_id, _bid)
            if _active_pid_for_briefs is None:
                _row_badge = "Personal"
            else:
                _row_badge = research_svc.brief_scope_badge(
                    _brief, _active_pname_for_briefs)
            _row_sub = research_svc.brief_row_sub(_brief, _row_badge)
            if st.button(
                _blabel,
                key=f"research-open-{_bid}",
                help=f"Open brief{_row_sub and ' · ' + _row_sub or ''}",
                disabled=_is_sel,
            ):
                try:
                    st.session_state.selected_brief_id = _bid
                except Exception:
                    pass
                st.rerun()
            if _row_sub:
                st.caption(_row_sub)
    if isinstance(_selected_brief_id, str) and _selected_brief_id:
        st.markdown('<div class="poka-divider"></div>',
                    unsafe_allow_html=True)
        _sel_brief = None
        try:
            _sel_brief = _user_store().get_brief(_selected_brief_id)
        except Exception:
            _sel_brief = None
        _sel_in_scope = research_svc.is_brief_in_scope(
            _sel_brief, _active_pid_for_briefs) if isinstance(
                _sel_brief, dict) else False
        if not isinstance(_sel_brief, dict) or not _sel_in_scope:
            st.markdown(
                '<p class="poka-empty">Brief unavailable.</p>',
                unsafe_allow_html=True,
            )
            if st.button("Back", key="research-close"):
                try:
                    st.session_state.selected_brief_id = None
                except Exception:
                    pass
                st.rerun()
        else:
            st.markdown(
                '<p class="poka-card-sub">Research Brief</p>',
                unsafe_allow_html=True,
            )
            _bq = str(_sel_brief.get("query", "")).strip() or "Untitled brief"
            st.markdown(
                f"<p><strong>{html.escape(_bq[:MAX_ERROR_SNIPPET_CHARS])}</strong></p>",
                unsafe_allow_html=True,
            )
            _bcreated = research_svc.format_brief_created(
                _sel_brief.get("created", 0.0))
            _scope_badge = research_svc.brief_scope_badge(
                _sel_brief, _active_pname_for_briefs
                if _active_pid_for_briefs else None)
            _scope_line = (
                f"In {_md_text(_scope_badge[:60])}."
                if _scope_badge != "Personal"
                else "In Personal.")
            if _bcreated:
                st.caption(f"{_bcreated} · {_scope_line}")
            else:
                st.caption(_scope_line)
            st.markdown(
                '<p class="poka-card-sub">Summary</p>',
                unsafe_allow_html=True,
            )
            _bexcerpt = _sel_brief.get("excerpt", "")
            if isinstance(_bexcerpt, str) and _bexcerpt.strip():
                st.markdown(
                    html.escape(_bexcerpt.strip()[:2000]).replace(
                        "[", "\\["),
                )
            else:
                st.caption("No summary captured.")
            _bsources = []
            _raw_bsrc = _sel_brief.get("sources", [])
            if isinstance(_raw_bsrc, list):
                for _s in _raw_bsrc:
                    _c = clean_source_record(_s)
                    if _c is not None:
                        _bsources.append(_c)
            if _bsources:
                st.markdown(
                    '<p class="poka-sources-head">Sources</p>',
                    unsafe_allow_html=True,
                )
                for _n, _rec in enumerate(_bsources, start=1):
                    _href = str(_rec.get("url", "")).replace(")", "%29")
                    st.markdown(
                        '<p class="poka-source">'
                        f'<span class="poka-source-n">[{_n}]</span> '
                        f'<a href="{html.escape(_href, quote=True)}" '
                        'target="_blank" rel="noopener noreferrer">'
                        f"{html.escape(str(_rec.get('title', '')))}</a> "
                        '<span class="poka-source-d">'
                        f"{html.escape(str(_rec.get('domain', '')))}</span>"
                        "</p>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No validated sources stored.")
            _gcol, _ccol = st.columns(2)
            with _gcol:
                if st.button(
                    "Generate document",
                    key=f"research-generate-{_sel_brief.get('id', '')}",
                    help="Build a Word document from this brief",
                ):
                    try:
                        _gen_meta = research_svc.generate_docx_from_brief(
                            _user_store(), _file_store(),
                            _sel_brief.get("id", ""))
                    except ValueError as e:
                        st.toast(str(e)[:MAX_ERROR_SNIPPET_CHARS])
                    except RuntimeError as e:
                        st.toast(str(e)[:MAX_ERROR_SNIPPET_CHARS])
                    except Exception:
                        st.toast("Could not generate document.")
                    else:
                        try:
                            _msgs_g = st.session_state.get(
                                "messages", [])
                            _cur_pid_g = st.session_state.get(
                                "current_project_id", None)
                            from ui.project_resources import open_bucket as _open_bucket_g
                            _brief_pid = _sel_brief.get(
                                "project_id", None)
                            _brief_bucket = (
                                _brief_pid
                                if isinstance(_brief_pid, str)
                                and _brief_pid in _valid_project_ids
                                else None)
                            if (isinstance(_msgs_g, list) and _msgs_g
                                    and _open_bucket_g(
                                        _cur_pid_g,
                                        _valid_project_ids) == _brief_bucket):
                                _msgs_g.append({
                                    "role": "assistant",
                                    "content": "Generated document from brief: "
                                    f"{str(_sel_brief.get('query', ''))[:MAX_DISPLAY_NAME_CHARS]}",
                                    "time": utcnow_iso(),
                                    "artifacts": [{
                                        "id": _gen_meta.id,
                                        "kind": _gen_meta.kind,
                                        "name": _gen_meta.display_name,
                                    }],
                                })
                                st.session_state.messages = _msgs_g
                                persist()
                        except Exception:
                            pass
                        st.toast("Document generated.")
                        st.rerun()
            with _ccol:
                if st.button("Back", key="research-close"):
                    try:
                        st.session_state.selected_brief_id = None
                    except Exception:
                        pass
                    st.rerun()
    _workspace_back_row()


def render_stats_view() -> None:
    """Main-workspace Stats view (moved from sidebar)."""
    st.markdown('<p class="section-label">Stats</p>', unsafe_allow_html=True)
    try:
        _outputs_count = len(_file_store().list_outputs())
    except StorageError:
        _outputs_count = 0
    try:
        _model_name = _active_model_name()
    except Exception:
        _model_name = ""
    st.markdown(
        '<div class="stats-box">'
        '<div class="poka-stat-row">'
        '<span class="poka-stat-key">Messages</span>'
        f'<span class="poka-stat-val">'
        f'{len(st.session_state.messages)}'
        "</span>"
        "</div>"
        '<div class="poka-stat-row">'
        '<span class="poka-stat-key">Artifacts</span>'
        f'<span class="poka-stat-val">'
        f'{_outputs_count}'
        "</span>"
        "</div>"
        '<div class="poka-stat-row">'
        '<span class="poka-stat-key">Active</span>'
        f'<span class="poka-stat-active">'
        f'{html.escape(_model_name)}'
        "</span>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    _workspace_back_row()


def render_workspace_view() -> None:
    """Render the selected main-workspace destination, if any.

    Returns immediately when no destination is selected (normal chat).
    Exactly one destination renders per run, so widget keys stay unique.
    """
    _sidebar_view = get_sidebar_view()
    if _sidebar_view is None:
        return
    if _sidebar_view == "research":
        render_research_view()
    elif _sidebar_view == "workflows":
        render_workflows_view()
    elif _sidebar_view == "memory":
        render_memory_view()
    elif _sidebar_view == "files":
        render_files_view()
    elif _sidebar_view == "artifacts":
        render_artifacts_view()
    elif _sidebar_view == "sources":
        render_sources_view()
    elif _sidebar_view == "stats":
        render_stats_view()


def render_files_view() -> None:
    """Main-workspace Files view (moved from sidebar).

    User-provided inputs (uploads, never generated). Keys, logic,
    ownership, and project derivation unchanged.
    """
    st.markdown('<p class="section-label">Files</p>', unsafe_allow_html=True)
    _bundle = _workspace_scope_bundle()
    _scope_id = _bundle["scope_id"]
    if _scope_id is None:
        # Personal: full registry, exactly as before.
        try:
            staged_uploads = _file_store().list_uploads()
        except StorageError:
            staged_uploads = []
        if staged_uploads:
            for _up in staged_uploads[:8]:
                st.markdown(
                    _upload_row_html(_up),
                    unsafe_allow_html=True,
                )
            if len(staged_uploads) > 8:
                st.caption(
                    f"Showing 8 of {len(staged_uploads)} staged files."
                )
        else:
            st.markdown(
                '<p class="poka-empty">No uploaded files yet — attach '
                "PDFs, CSVs, or photos with + to analyze them</p>",
                unsafe_allow_html=True,
            )
    else:
        # Project: derived view over member conversations.
        _scoped_metas = []
        for _uid in _bundle["upload_ids"]:
            try:
                _umeta = _file_store().get_upload(_uid)
            except StorageError:
                _umeta = None
            if _umeta is not None:
                _scoped_metas.append(_umeta)
        if _scoped_metas:
            for _up in _scoped_metas[:8]:
                st.markdown(
                    _upload_row_html(_up),
                    unsafe_allow_html=True,
                )
            if len(_scoped_metas) > 8:
                st.caption(
                    f"Showing 8 of {len(_scoped_metas)} files."
                )
        else:
            st.markdown(
                '<p class="poka-empty">No files in this project yet. '
                "Files attached in this project's conversations "
                "appear here.</p>",
                unsafe_allow_html=True,
            )
    _workspace_back_row()


def render_memory_view() -> None:
    """Main-workspace Memory view (moved from sidebar).

    Keys, logic, and persistence unchanged — only render location moved.
    """
    st.markdown('<p class="section-label">Memory</p>', unsafe_allow_html=True)
    vault_rows = _vault_rows()
    _notes_set = bool(str(st.session_state.get("memory_notes", "") or "").strip())
    st.caption(
        f"Saved notes · {'set' if _notes_set else 'none'} — "
        f"Remembered facts · {len(vault_rows)}"
    )
    st.markdown(
        '<p class="poka-card-sub">Saved notes</p>',
        unsafe_allow_html=True,
    )
    st.caption("Notes you chose to save.")
    notes_in = st.text_area(
        "Memory notes",
        value=st.session_state.get(
            "memory_notes",
            "",
        ),
        height=UI_TEXT_AREA_HEIGHT,
        placeholder="e.g. Prefers concise answers, works in Berlin…",
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
    st.markdown('<div class="poka-divider"></div>', unsafe_allow_html=True)
    vault_head = (
        f"Remembered facts ({len(vault_rows)})"
        if vault_rows
        else "Remembered facts"
    )
    st.markdown(
        f'<p class="poka-card-sub">{vault_head}</p>',
        unsafe_allow_html=True,
    )
    st.caption("Details Poka extracted from conversation.")
    if not vault_rows:
        st.markdown(
            '<p class="poka-empty">No saved memories yet. '
            "Poka remembers useful details you share, like "
            "preferences or projects — review or remove them "
            "here anytime.</p>",
            unsafe_allow_html=True,
        )
    else:
        for _key, _ref, _fact in vault_rows[:15]:
            _row_col, _del_col = st.columns([5, 1])
            with _row_col:
                st.markdown(
                    _mem_row_html(_fact),
                    unsafe_allow_html=True,
                )
            with _del_col:
                _value = str(_fact.get("value", "this memory"))
                if _del_col.button(
                    "×",
                    key=f"forget-fact-{_key}",
                    help=f"Forget: {_md_text(_value[:40])}",
                ):
                    if delete_memory_fact(str(_ref)):
                        st.toast("Forgotten.")
                    else:
                        st.toast("Nothing matched that.")
                    st.rerun()
        if len(vault_rows) > 15:
            st.caption(
                f"Showing 15 of {len(vault_rows)} — "
                "use Forget below to remove more."
            )
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
    _workspace_back_row()


def render_workflows_view() -> None:
    """Main-workspace Workflows chooser + panels (moved from sidebar).

    Orchestration only: Research sets pending_prompt + force_search
    and lets the normal send flow execute; Document Analysis sets
    pending_prompt and lets the normal flow consume staged
    attachments. Status text derives from real messages/briefs —
    never fabricated. No parallel transcript, store, or agent.
    """
    st.markdown('<p class="section-label">Workflows</p>', unsafe_allow_html=True)
    _selected_wf = workflow_svc.get_selected_workflow(st.session_state)
    try:
        _wf_scope_name = workflow_svc.conversation_scope_label(
            _user_store(), st.session_state.get("current_project_id", None))
    except Exception:
        _wf_scope_name = "Personal"
    if st.button(
        "Research",
        key="workflow-select-research",
        help="Search the web, save your findings, and turn them into a document",
        disabled=_selected_wf == workflow_svc.WORKFLOW_RESEARCH,
    ):
        st.session_state.selected_workflow = workflow_svc.WORKFLOW_RESEARCH
        st.rerun()
    if _selected_wf != workflow_svc.WORKFLOW_RESEARCH:
        st.caption("Search the web and save findings")
    if st.button(
        "Document Analysis",
        key="workflow-select-docs",
        help="Analyze one or more uploaded files and turn the findings into a useful summary",
        disabled=_selected_wf == workflow_svc.WORKFLOW_DOC_ANALYSIS,
    ):
        st.session_state.selected_workflow = workflow_svc.WORKFLOW_DOC_ANALYSIS
        st.rerun()
    if _selected_wf != workflow_svc.WORKFLOW_DOC_ANALYSIS:
        st.caption("Analyze uploaded files")
    if _selected_wf is None:
        st.caption("Search the web, save your findings, and turn them into a document. "
                   "Or analyze uploaded files into a useful summary.")
    elif _selected_wf == workflow_svc.WORKFLOW_RESEARCH:
        st.markdown('<p class="poka-card-sub">Research</p>', unsafe_allow_html=True)
        if _wf_scope_name == "Personal":
            st.caption("Personal")
        else:
            st.caption(f"In {_md_text(_wf_scope_name[:30])}.")
        st.markdown("What would you like to research?")
        st.caption("Ask a focused question. A good question names the topic and what you want to learn.")
        _wf_q = st.text_input(
            "Research question",
            value=str(st.session_state.get("workflow_research_question", "") or ""),
            placeholder="e.g. What are the latest advances in offshore wind?",
            label_visibility="collapsed",
            key="workflow-research-question",
        )
        if st.button("Research", key="workflow-research-run",
                     help="Run a web search for this question"):
            try:
                _cleaned_q = workflow_svc.validate_research_question(_wf_q)
            except ValueError as e:
                st.toast(str(e)[:MAX_ERROR_SNIPPET_CHARS])
            else:
                try:
                    _wf_msg_len = len(st.session_state.get("messages", []) or [])
                except Exception:
                    _wf_msg_len = 0
                if workflow_svc.research_already_submitted(
                        st.session_state, _cleaned_q, _wf_msg_len):
                    st.toast("Already running — see the latest result in chat.")
                else:
                    st.session_state.workflow_research_question = _cleaned_q
                    st.session_state.pending_prompt = _cleaned_q
                    st.session_state.force_search = True
                    workflow_svc.mark_research_submitted(
                        st.session_state, _cleaned_q, _wf_msg_len)
                    st.rerun()
        try:
            _wf_failed = bool(st.session_state.get("last_failed", False))
        except Exception:
            _wf_failed = False
        try:
            _wf_pending = bool(str(st.session_state.get("pending_prompt", "") or "").strip())
        except Exception:
            _wf_pending = False
        try:
            _wf_status = workflow_svc.research_status(
                st.session_state.get("messages", []), _user_store(),
                st.session_state.get("current_project_id", None))
        except Exception:
            _wf_status = "needs_question"
        if _wf_failed:
            st.caption("Search failed — use Retry in chat, or Continue in chat.")
        elif _wf_pending:
            st.caption("Researching…")
        elif _wf_status == "saved":
            st.caption("Research complete — Saved as Research Brief. "
                       "Open it in Research, or Generate document there.")
        elif _wf_status == "result_ready":
            st.caption("Your research is ready — choose Save as Research Brief under the answer.")
        else:
            st.caption("Enter a question above, then choose Research.")
        if st.button("Continue in chat", key="workflow-exit",
                     help="Exit workflow — your chat, files, briefs, and artifacts stay"):
            workflow_svc.exit_workflow(st.session_state)
            st.rerun()
    else:
        st.markdown('<p class="poka-card-sub">Document Analysis</p>', unsafe_allow_html=True)
        if _wf_scope_name == "Personal":
            st.caption("Personal")
        else:
            st.caption(f"In {_md_text(_wf_scope_name[:30])}.")
        st.caption("Upload one or more files to analyze them.")
        try:
            _wf_staged = _pending_list()
        except Exception:
            _wf_staged = []
        try:
            _wf_doc_pending = bool(str(st.session_state.get("pending_prompt", "") or "").strip())
        except Exception:
            _wf_doc_pending = False
        if not _wf_staged:
            st.markdown(
                '<p class="poka-empty">No files attached</p>',
                unsafe_allow_html=True,
            )
            st.caption("Choose files from the attachment button (+) to begin analysis.")
        else:
            st.caption(f"{len(_wf_staged)} file{'s' if len(_wf_staged) != 1 else ''} attached — "
                       "all staged files will be analyzed together.")
        _wf_dq = st.text_input(
            "Analysis question (optional)",
            value=str(st.session_state.get("workflow_doc_question", "") or ""),
            placeholder="Optional question about the files",
            label_visibility="collapsed",
            key="workflow-doc-question",
        )
        _wf_summ = st.button("Summarize", key="workflow-docs-summarize",
                             help="Analyze files: summarize the attached documents")
        _wf_find = st.button("Key findings", key="workflow-docs-findings",
                             help="Analyze files: list the key findings")
        _wf_comp = st.button("Compare", key="workflow-docs-compare",
                             help="Analyze files: compare the attached documents")
        _wf_template = None
        if _wf_summ:
            _wf_template = "summarize"
        elif _wf_find:
            _wf_template = "findings"
        elif _wf_comp:
            _wf_template = "compare"
        if _wf_template is not None:
            try:
                _wf_staged_now = _pending_list()
            except Exception:
                _wf_staged_now = []
            if not _wf_staged_now:
                st.toast("Attach at least one file first.")
            else:
                try:
                    _wf_doc_len = len(st.session_state.get("messages", []) or [])
                except Exception:
                    _wf_doc_len = 0
                _wf_prompt = workflow_svc.build_doc_analysis_prompt(_wf_template, _wf_dq)
                if workflow_svc.doc_already_submitted(
                        st.session_state, _wf_prompt, len(_wf_staged_now), _wf_doc_len):
                    st.toast("Already analyzing — see the latest result in chat.")
                else:
                    st.session_state.workflow_doc_question = str(_wf_dq or "")
                    st.session_state.pending_prompt = _wf_prompt
                    workflow_svc.mark_doc_submitted(
                        st.session_state, _wf_prompt, len(_wf_staged_now), _wf_doc_len)
                    st.rerun()
        try:
            _wf_doc_failed = bool(st.session_state.get("last_failed", False))
        except Exception:
            _wf_doc_failed = False
        try:
            _wf_doc_state = workflow_svc.doc_status(
                st.session_state.get("messages", []), _wf_staged)
        except Exception:
            _wf_doc_state = "needs_files"
        if _wf_doc_failed:
            st.caption("Analysis failed — use Retry in chat, or Continue in chat.")
        elif _wf_doc_pending:
            st.caption("Analyzing files…")
        elif _wf_doc_state == "complete":
            st.caption("Analysis complete — Continue in chat, or Generate document from the result.")
        elif _wf_doc_state == "ready":
            st.caption("Files ready — choose Summarize, Key findings, or Compare.")
        if st.button("Continue in chat", key="workflow-exit",
                     help="Exit workflow — your chat, files, briefs, and artifacts stay"):
            workflow_svc.exit_workflow(st.session_state)
            st.rerun()
    _workspace_back_row()
