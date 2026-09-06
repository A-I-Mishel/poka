"""Phase 6B core capability: research briefs + artifact regeneration.

Pure helpers plus thin generation wrappers. All stored data is
untrusted: IDs are validated, sources re-validated, specs re-cleaned,
project membership re-resolved. No markdown parsing, no eval/exec,
no second registry.

Duplicate-save rule (documented):
- Service ``create_brief_from_message`` allows intentional duplicates:
  each call creates a new brief with a new stable ID.
- UI disables the Save button after a successful save in the same
  session (session marker) so repeated clicks do not create accidental
  duplicates. Reopening the chat allows an intentional second save.

Query semantics:
- The brief query is the nearest preceding user message content (the
  actual research request). It is never reconstructed from the
  assistant response or source titles. When no preceding user message
  exists, Save is disabled. Queries are stripped and truncated to
  MAX_BRIEF_QUERY_CHARS to respect storage bounds.

Excerpt semantics:
- Bounded head slice of the assistant answer
  (``content.strip()[:MAX_BRIEF_EXCERPT_CHARS]``), matching the
  existing silent-slice convention used by storage cleaners
  (titles, brief records). No storage limit is ever exceeded.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from services.limits import MAX_BRIEF_EXCERPT_CHARS, MAX_BRIEF_QUERY_CHARS
from services.storage import clean_generation_spec, clean_source_record, is_valid_id

#: Cap for the sidebar Research list (compact, Streamlit-friendly).
MAX_VISIBLE_BRIEFS: int = 8


def validated_brief_sources(message: Any) -> List[Dict[str, str]]:
    """Validated source records from structured provenance (max 6)."""
    if not isinstance(message, dict):
        return []
    stored = message.get("sources")
    if not isinstance(stored, list):
        return []
    out: List[Dict[str, str]] = []
    for entry in stored:
        cleaned = clean_source_record(entry)
        if cleaned is not None:
            out.append(cleaned)
        if len(out) >= 6:
            break
    return out


def is_brief_eligible(message: Any) -> bool:
    """True only for search-backed answers with trustworthy provenance.

    Requires: assistant role, ``search_executed is True``, and at least
    one validated structured source. Intent alone (``searched``),
    markdown text (never parsed), and the literal string
    "Sources consulted:" are never used as signals.
    """
    if not isinstance(message, dict):
        return False
    if message.get("role") != "assistant":
        return False
    if message.get("search_executed") is not True:
        return False
    return len(validated_brief_sources(message)) > 0


def find_brief_query(messages: Any, assistant_index: int) -> Optional[str]:
    """Return the nearest preceding user request, or None.

    Walks backwards from ``assistant_index`` to find the actual user
    research request. Returns the stripped content truncated to
    MAX_BRIEF_QUERY_CHARS, or None when no safe query exists.
    """
    if not isinstance(messages, list):
        return None
    if not isinstance(assistant_index, int):
        return None
    if assistant_index < 0 or assistant_index >= len(messages):
        return None
    for pos in range(assistant_index - 1, -1, -1):
        candidate = messages[pos]
        if not isinstance(candidate, dict):
            continue
        if candidate.get("role") != "user":
            continue
        content = candidate.get("content", "")
        if not isinstance(content, str):
            continue
        stripped = content.strip()
        if not stripped:
            continue
        return stripped[:MAX_BRIEF_QUERY_CHARS]
    return None


def build_brief_excerpt(assistant_content: Any) -> str:
    """Bounded excerpt from an assistant answer (head slice)."""
    if not isinstance(assistant_content, str):
        return ""
    return assistant_content.strip()[:MAX_BRIEF_EXCERPT_CHARS]


def resolve_brief_project_id(user_store: Any, current_project_id: Any) -> Optional[str]:
    """Resolve the open conversation's project for brief association.

    Returns the project ID only when it resolves to an existing,
    non-archived project in the caller's own registry. Returns None
    for Personal (no fake project) and for archived projects (new
    briefs fall back to Personal rather than reviving an archived
    bucket). Never trusts active_project_id; callers must pass the
    conversation's own ``current_project_id``. Returns None for
    missing/malformed IDs; unknown well-formed IDs are surfaced by
    the caller as an explicit error (never silently Personal).
    Never raises.
    """
    try:
        if not is_valid_id(current_project_id):
            return None
        record = user_store.get_project(current_project_id)
    except Exception:
        return None
    if isinstance(record, dict) and not record.get("archived", False):
        return str(record["id"])
    if isinstance(record, dict) and record.get("archived", False):
        return None
    return None


def create_brief_from_message(
    user_store: Any,
    messages: Any,
    assistant_index: int,
    current_project_id: Any = None,
) -> Dict[str, Any]:
    """Create a brief from a search-backed assistant message.

    Uses only trustworthy data: query from the preceding user message,
    sources from structured provenance, excerpt as a bounded slice.
    Raises ValueError with a user-safe message when provenance, query,
    or project resolution fails.
    """
    if not isinstance(messages, list) or not (0 <= assistant_index < len(messages)):
        raise ValueError("Response could not be saved as a brief.")
    assistant_msg = messages[assistant_index]
    if not is_brief_eligible(assistant_msg):
        raise ValueError("Only search-backed answers can be saved as briefs.")
    query = find_brief_query(messages, assistant_index)
    if query is None or not query.strip():
        raise ValueError("Original research request could not be recovered.")
    sources = validated_brief_sources(assistant_msg)
    excerpt = build_brief_excerpt(assistant_msg.get("content", ""))
    # Explicit unknown project IDs must fail loudly (never silently
    # Personal): a well-formed ID that resolves to nothing means the
    # conversation membership cannot be trusted.
    if (is_valid_id(current_project_id)
            and resolve_brief_project_id(user_store, current_project_id) is None):
        try:
            _exists = user_store.get_project(current_project_id)
        except Exception:
            _exists = None
        if _exists is None:
            raise ValueError("Unknown project.")
    pid = resolve_brief_project_id(user_store, current_project_id)
    return user_store.create_brief(query, sources, excerpt, pid)


def personal_briefs(user_store: Any, limit: int = MAX_VISIBLE_BRIEFS) -> List[Dict[str, Any]]:
    """Personal/unassigned briefs, newest first, capped."""
    try:
        all_briefs = user_store.list_briefs()
    except Exception:
        return []
    personal = [b for b in all_briefs if "project_id" not in b]
    return personal[: max(0, limit)]


def visible_briefs_for_scope(
    user_store: Any,
    active_project_id: Any,
    limit: int = MAX_VISIBLE_BRIEFS,
) -> List[Dict[str, Any]]:
    """Briefs visible in one workspace scope, newest first, capped.

    Active project scope shows only briefs with that exact project_id
    (validated active). Personal scope shows only unassigned briefs.
    Archived/orphan briefs appear in neither list (still stored and
    retrievable by ID); nothing is rewritten.
    """
    try:
        if isinstance(active_project_id, str) and active_project_id:
            record = user_store.get_project(active_project_id)
            if isinstance(record, dict) and not record.get("archived", False):
                try:
                    scoped = user_store.list_briefs(record["id"])
                except Exception:
                    return []
                return scoped[: max(0, limit)]
    except Exception:
        pass
    return personal_briefs(user_store, limit)


def format_brief_created(created: Any) -> str:
    """Human date for a brief timestamp; "" when unknown."""
    try:
        moment = datetime.fromtimestamp(float(created))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
    return moment.strftime("%b %d, %Y")


def brief_display_title(brief: Any, limit: int = 60) -> str:
    """Short query-derived title for list rows (never raises)."""
    try:
        query = str(brief.get("query", "")).strip() if isinstance(brief, dict) else ""
    except Exception:
        query = ""
    if not query:
        return "Untitled brief"
    flat = " ".join(query.split())
    if len(flat) <= limit:
        return flat
    return flat[: max(0, limit - 1)].rstrip() + "…"


def is_brief_in_scope(brief: Any, active_project_id: Any) -> bool:
    """True when a brief belongs to the given workspace scope.

    Personal scope (None/empty) matches only briefs without
    ``project_id``. Project scope matches only exact
    ``project_id`` equality. Orphan/archived IDs never leak into
    unrelated scopes. Never raises, never rewrites.
    """
    try:
        if not isinstance(brief, dict):
            return False
        pid = brief.get("project_id", None)
        if isinstance(active_project_id, str) and active_project_id:
            return pid == active_project_id
        return "project_id" not in brief
    except Exception:
        return False


def is_selected_brief(selected_id: Any, brief_id: Any) -> bool:
    """True when two stable brief IDs identify the same brief."""
    try:
        return (isinstance(selected_id, str) and isinstance(brief_id, str)
                and bool(selected_id) and selected_id == brief_id)
    except Exception:
        return False


def brief_scope_badge(brief: Any, project_name: Any = None) -> str:
    """Compact scope badge text: project name or 'Personal'."""
    try:
        if not isinstance(brief, dict) or "project_id" not in brief:
            return "Personal"
        name = str(project_name or "").strip()
        if not name:
            return "Project"
        flat = " ".join(name.split())
        return flat[:30] if len(flat) <= 30 else flat[:29].rstrip() + "…"
    except Exception:
        return "Personal"


def brief_source_count(brief: Any) -> int:
    """Validated source count for list metadata (never raises)."""
    try:
        raw = brief.get("sources", []) if isinstance(brief, dict) else []
        if not isinstance(raw, list):
            return 0
        return sum(1 for s in raw if clean_source_record(s) is not None)
    except Exception:
        return 0


def brief_row_sub(brief: Any, scope_label: Any = None) -> str:
    """One-line list metadata: date · scope · N sources."""
    try:
        bits: List[str] = []
        date_str = format_brief_created(
            brief.get("created", 0.0) if isinstance(brief, dict) else 0.0)
        if date_str:
            bits.append(date_str)
        scope = str(scope_label or "").strip()
        if scope:
            bits.append(scope)
        count = brief_source_count(brief)
        if count:
            bits.append(f"{count} source{'s' if count != 1 else ''}")
        return " · ".join(bits)
    except Exception:
        return ""


def sort_artifacts_newest_first(metas: Any) -> List[Any]:
    """Return artifact metas sorted newest-first (never mutates input)."""
    try:
        items = list(metas or [])
    except Exception:
        return []
    try:
        return sorted(items, key=lambda m: float(getattr(m, "created", 0.0) or 0.0),
                      reverse=True)
    except Exception:
        return items


def brief_markdown_for_docx(brief: Any) -> Tuple[str, str]:
    """Build (title, markdown_text) for DOCX generation from a brief.

    All inputs are treated as untrusted data: truncated to safe sizes
    and passed as plain strings to the existing builder. Never builds
    commands, never eval/exec.
    """
    if not isinstance(brief, dict):
        raise ValueError("Brief not found.")
    query = brief.get("query", "")
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        raise ValueError("Brief has no research question.")
    excerpt = brief.get("excerpt", "")
    excerpt = excerpt if isinstance(excerpt, str) else ""
    excerpt = excerpt.strip()[:MAX_BRIEF_EXCERPT_CHARS]
    raw_sources = brief.get("sources", [])
    sources: List[Dict[str, str]] = []
    if isinstance(raw_sources, list):
        for entry in raw_sources:
            cleaned = clean_source_record(entry)
            if cleaned is not None:
                sources.append(cleaned)
            if len(sources) >= 6:
                break
    title = query[:120].strip() or "Research Brief"
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Research question")
    lines.append("")
    lines.append(query[:MAX_BRIEF_QUERY_CHARS])
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(excerpt if excerpt else "No summary captured.")
    lines.append("")
    if sources:
        lines.append("## Sources")
        lines.append("")
        for src in sources:
            safe_title = " ".join(str(src.get("title", "")).split())[:120] or src.get("domain", "")
            lines.append(f"- {safe_title} — {src.get('domain', '')}")
            lines.append(f"  {src.get('url', '')}")
        lines.append("")
    else:
        lines.append("## Sources")
        lines.append("")
        lines.append("No validated sources stored.")
        lines.append("")
    markdown_text = "\n".join(lines)[:20000]
    return title, markdown_text


def _new_outputs_since(file_store: Any, before_ids: Any) -> List[Any]:
    try:
        metas = file_store.list_outputs()
    except Exception:
        return []
    if not isinstance(before_ids, set):
        return []
    return [m for m in metas if getattr(m, "id", None) not in before_ids]


def generate_docx_from_brief(user_store: Any, file_store: Any, brief_id: Any) -> Any:
    """Generate a DOCX from a saved brief via build_document.

    Ownership-checked (brief must belong to the caller). Uses the
    existing generation quota path (build_document claims the slot).
    Returns the new OutputMeta. Raises ValueError for unknown briefs,
    RuntimeError for generation failures (no fake artifact, originals
    untouched).
    """
    brief = None
    try:
        brief = user_store.get_brief(brief_id)
    except Exception:
        brief = None
    if brief is None:
        raise ValueError("Brief not found.")
    title, markdown_text = brief_markdown_for_docx(brief)
    try:
        before = {m.id for m in file_store.list_outputs()}
    except Exception:
        before = set()
    from tools.docx_tool import build_document

    out = build_document.invoke({"title": title, "markdown_text": markdown_text})
    if isinstance(out, str) and out.startswith("STATUS="):
        raise RuntimeError(out[:500])
    fresh = _new_outputs_since(file_store, before)
    if not fresh:
        raise RuntimeError("STATUS=FAILED tool=build_document: no artifact registered.")
    fresh.sort(key=lambda m: getattr(m, "created", 0.0), reverse=True)
    return fresh[0]


def can_regenerate(file_store: Any, artifact_id: Any) -> bool:
    """True only for owned artifacts with a currently-valid spec."""
    try:
        meta = file_store.get_output(artifact_id)
    except Exception:
        return False
    if meta is None:
        return False
    spec = getattr(meta, "spec", None)
    return clean_generation_spec(spec) is not None


def get_valid_spec(file_store: Any, artifact_id: Any) -> Optional[Dict[str, Any]]:
    """Ownership-checked, re-validated spec, or None."""
    try:
        meta = file_store.get_output(artifact_id)
    except Exception:
        return None
    if meta is None:
        return None
    return clean_generation_spec(getattr(meta, "spec", None))


def regenerate_artifact(file_store: Any, artifact_id: Any) -> Any:
    """Re-run a stored generation spec via the allowlisted tool.

    Loads through ownership checks, re-validates the spec, dispatches
    only to the exact recorded tool with its exact expected fields.
    Creates a NEW artifact (new ID, timestamp, file); the original is
    never overwritten or deleted. Quota applies via the tool gate.
    Raises ValueError for unknown/legacy/tampered specs, RuntimeError
    for execution failures (original preserved).
    """
    try:
        meta = file_store.get_output(artifact_id)
    except Exception:
        meta = None
    if meta is None:
        raise ValueError("Artifact not found.")
    cleaned = clean_generation_spec(getattr(meta, "spec", None))
    if cleaned is None:
        raise ValueError("This file cannot be regenerated.")
    tool_name = cleaned["tool"]
    spec_input = cleaned["input"]
    try:
        before = {m.id for m in file_store.list_outputs()}
    except Exception:
        before = set()
    if tool_name == "create_docx":
        from tools.docx_tool import create_docx

        out = create_docx.invoke(dict(spec_input))
    elif tool_name == "build_document":
        from tools.docx_tool import build_document

        out = build_document.invoke(dict(spec_input))
    elif tool_name == "create_pptx":
        from tools.pptx_tool import create_pptx

        out = create_pptx.invoke(dict(spec_input))
    elif tool_name == "build_presentation":
        from tools.pptx_tool import build_presentation

        out = build_presentation.invoke(dict(spec_input))
    else:  # pragma: no cover — cleaner already rejects unknown tools
        raise ValueError("This file cannot be regenerated.")
    if isinstance(out, str) and out.startswith("STATUS="):
        raise RuntimeError(out[:500])
    fresh = _new_outputs_since(file_store, before)
    if not fresh:
        raise RuntimeError("STATUS=FAILED: no artifact registered.")
    fresh.sort(key=lambda m: getattr(m, "created", 0.0), reverse=True)
    return fresh[0]
