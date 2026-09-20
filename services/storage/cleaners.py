"""Load-path record validators: unknown keys dropped, bad records rejected.

Every cleaner returns None for unusable input (never raises, never
coerces) so one malformed entry cannot sink a whole registry.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from services.storage.ids import (
    ATTACH_KINDS,
    MAX_MODEL_NAME_LEN,
    MAX_MSGS_PER_CHAT,
    MAX_PROJECT_NAME_LEN,
    MAX_SOURCES,
    MAX_SOURCE_DOMAIN_LEN,
    MAX_SOURCE_TITLE_LEN,
    MAX_SOURCE_URL_LEN,
    MAX_TOOL_NAME_LEN,
    MAX_TOOL_NAMES,
    RESPONSE_MODES,
    _SOURCE_URL_SCHEMES,
    _SPEC_TOOLS,
    is_valid_id,
)


def _clean_attachment(value: Any) -> Optional[Dict[str, str]]:
    if not isinstance(value, dict):
        return None
    upload_id = value.get("id")
    kind = value.get("kind")
    name = value.get("name", "")
    if not isinstance(upload_id, str) or not upload_id:
        return None
    if kind not in ATTACH_KINDS:
        return None
    if not isinstance(name, str):
        return None
    return {"id": upload_id, "kind": kind, "name": name[:120]}


def _clean_artifact(value: Any) -> Optional[Dict[str, str]]:
    """Keep a message→artifact link ({id,kind,name}); None when unusable."""
    if not isinstance(value, dict):
        return None
    file_id = value.get("id")
    kind = value.get("kind")
    name = value.get("name", "")
    if not isinstance(file_id, str) or not file_id:
        return None
    if kind not in ("pptx", "docx", "pdf", "md", "doc", "html", "file"):
        return None
    if not isinstance(name, str) or not name:
        return None
    return {"id": file_id, "kind": kind, "name": name[:120]}


def _clean_tool_names(value: Any) -> Optional[List[str]]:
    """Keep a list of safe tool names; None when absent or unusable."""
    if not isinstance(value, list):
        return None
    names = [
        t[:MAX_TOOL_NAME_LEN]
        for t in value
        if isinstance(t, str) and t
    ]
    if not names:
        return None
    return names[:MAX_TOOL_NAMES]


def clean_source_record(value: Any) -> Optional[Dict[str, str]]:
    """Validate one persisted source record; None when unusable.

    Requires an http(s) URL without whitespace/control characters.
    Title falls back to the domain; domain is recomputed from the URL
    so stored records cannot smuggle mismatched metadata.
    """
    if not isinstance(value, dict):
        return None
    url = value.get("url", "")
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or len(url) > MAX_SOURCE_URL_LEN:
        return None
    if any(ch in url for ch in (" ", "\t", "\n", "\r", "\x00")):
        return None
    try:
        parts = urlparse(url)
    except Exception:
        return None
    if parts.scheme.lower() not in _SOURCE_URL_SCHEMES or not parts.netloc:
        return None
    title = value.get("title", "")
    title = str(title).strip()[:MAX_SOURCE_TITLE_LEN] if isinstance(title, str) else ""
    domain = parts.netloc.lower()[:MAX_SOURCE_DOMAIN_LEN]
    return {"title": title or domain, "url": url, "domain": domain}


def clean_generation_spec(value: Any) -> Optional[Dict[str, Any]]:
    """Validate an artifact generation spec; None when unusable.

    A spec is bounded opaque DATA ({kind, tool, input, created}) that a
    future phase may use to reproduce a generation. Unknown tools,
    kind/tool mismatches, unknown or non-string fields, oversize
    payloads, and bad timestamps are all rejected — never coerced —
    so an invalid spec can never masquerade as a reproducible one.
    """
    from services.limits import MAX_SPEC_STRING_CHARS, MAX_SPEC_TOTAL_CHARS

    if not isinstance(value, dict):
        return None
    kind = value.get("kind", "")
    tool = value.get("tool", "")
    if kind not in ("pptx", "docx", "pdf", "md", "doc", "html") or not isinstance(tool, str):
        return None
    expected = _SPEC_TOOLS.get(tool)
    if expected is None or expected[0] != kind:
        return None
    raw_input = value.get("input", None)
    if not isinstance(raw_input, dict):
        return None
    if set(raw_input.keys()) != expected[1]:
        return None
    cleaned_input: Dict[str, str] = {}
    total = 0
    for key in sorted(expected[1]):
        field = raw_input.get(key, "")
        if not isinstance(field, str) or not field.strip():
            return None
        if len(field) > MAX_SPEC_STRING_CHARS:
            return None
        total += len(field)
        if total > MAX_SPEC_TOTAL_CHARS:
            return None
        cleaned_input[key] = field
    created = value.get("created", None)
    if (not isinstance(created, (int, float)) or isinstance(created, bool)
            or not created >= 0):
        return None
    return {"kind": kind, "tool": tool, "input": cleaned_input,
            "created": float(created)}


def clean_messages(messages: Any) -> List[Dict[str, Any]]:
    """Validate/trim a message list.

    Preserves role/content/time/image/images/attachments plus optional
    assistant metadata (model/mode/searched/search_executed/tools/sources)
    and assistant artifact links. Unknown keys are dropped; legacy
    messages without metadata pass through unchanged.
    """
    cleaned: List[Dict[str, Any]] = []
    if isinstance(messages, list):
        for m in messages:
            if (
                not isinstance(m, dict)
                or m.get("role") not in ("user", "assistant")
                or not isinstance(m.get("content"), str)
            ):
                continue
            entry: Dict[str, Any] = {"role": m["role"], "content": m["content"]}
            if isinstance(m.get("time"), str):
                entry["time"] = m["time"]
            if m.get("failed") is True:
                # Failed-turn marker (persisted user request + error bubble):
                # regenerating it retries in place, so the flag must survive.
                entry["failed"] = True
            if isinstance(m.get("image"), str):
                entry["image"] = m["image"]
            if isinstance(m.get("images"), list):
                images = [str(p) for p in m["images"] if isinstance(p, str)]
                if images:
                    entry["images"] = images[:8]
            if isinstance(m.get("attachments"), list):
                atts = [_clean_attachment(a) for a in m["attachments"]]
                atts = [a for a in atts if a is not None]
                if atts:
                    entry["attachments"] = atts[:8]
            if isinstance(m.get("artifacts"), list):
                arts = [_clean_artifact(a) for a in m["artifacts"]]
                arts = [a for a in arts if a is not None]
                if arts:
                    entry["artifacts"] = arts[:8]
            if isinstance(m.get("model"), str) and m["model"]:
                entry["model"] = m["model"][:MAX_MODEL_NAME_LEN]
            if m.get("mode") in RESPONSE_MODES:
                entry["mode"] = m["mode"]
            if isinstance(m.get("searched"), bool):
                entry["searched"] = m["searched"]
            if isinstance(m.get("search_executed"), bool):
                entry["search_executed"] = m["search_executed"]
            if isinstance(m.get("sources"), list):
                srcs = [clean_source_record(s) for s in m["sources"]]
                srcs = [s for s in srcs if s is not None]
                if srcs:
                    entry["sources"] = srcs[:MAX_SOURCES]
            cleaned_tools = _clean_tool_names(m.get("tools"))
            if cleaned_tools is not None:
                entry["tools"] = cleaned_tools
            if isinstance(m.get("fallback"), dict):
                fb = m["fallback"]
                entry["fallback"] = {
                    "requested": str(fb.get("requested", ""))[:64],
                    "reason": str(fb.get("reason", ""))[:128],
                }
            if isinstance(m.get("corrections"), list):
                corr = []
                for pair in m["corrections"][:5]:
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        o, n = str(pair[0])[:32], str(pair[1])[:32]
                        if o and n and o.lower() != n.lower():
                            corr.append([o, n])
                if corr:
                    entry["corrections"] = corr
            if isinstance(m.get("pending_approvals"), list):
                pa = []
                for a in m["pending_approvals"][:8]:
                    if isinstance(a, dict) and a.get("id") and a.get("tool"):
                        pa.append({"id": str(a["id"])[:64], "tool": str(a["tool"])[:64], "summary": str(a.get("summary", ""))[:120]})
                if pa:
                    entry["pending_approvals"] = pa
            cleaned.append(entry)
    return cleaned[-MAX_MSGS_PER_CHAT:]


def _clean_chat_record(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    record: Dict[str, Any] = {
        "title": str(value.get("title", "Untitled"))[:60],
        "messages": clean_messages(value.get("messages", [])),
    }
    if is_valid_id(value.get("id")):
        record["id"] = value["id"]
    if is_valid_id(value.get("project_id")):
        record["project_id"] = value["project_id"]
    # ponytail: episodic summaries (attached at archive for long chats)
    # must survive save/load round-trips instead of being silently
    # dropped; bounded like the writer (EPISODIC_SUMMARY_CHARS). No
    # behavior change for records without one.
    summary = value.get("summary")
    if isinstance(summary, str) and summary.strip():
        record["summary"] = summary.strip()[:2000]
    # ponytail: legacy chats lack updated_at — drop it, sort treats missing as oldest
    updated = value.get("updated_at")
    if isinstance(updated, str) and updated.strip():
        record["updated_at"] = updated.strip()[:64]
    return record


def find_chat_by_id(chats: Any, chat_id: Any) -> Optional[Dict[str, Any]]:
    """Resolve a conversation by stable ID within one user's list.

    Returns a copy, or None for malformed IDs and misses. Never raises.
    Index-based access remains for existing UI paths; no new feature
    may persist list indexes as references.
    """
    if not is_valid_id(chat_id):
        return None
    if not isinstance(chats, list):
        return None
    for chat in chats:
        if isinstance(chat, dict) and chat.get("id") == chat_id:
            return dict(chat)
    return None


def _clean_brief_record(value: Any) -> Optional[Dict[str, Any]]:
    """Validate one brief record; None when identity/content fields fail.

    Query must be present and bounded; excerpt must be a bounded string;
    sources keep only valid records (capped); project_id keeps only
    valid-format IDs (existence is checked at creation, orphans load
    as-is like conversations). Bad created coerces to 0.0.
    """
    from services.limits import MAX_BRIEF_EXCERPT_CHARS, MAX_BRIEF_QUERY_CHARS

    if not isinstance(value, dict):
        return None
    bid = value.get("id")
    if not is_valid_id(bid):
        return None
    query = value.get("query", "")
    if not isinstance(query, str) or not query.strip():
        return None
    excerpt = value.get("excerpt", "")
    if not isinstance(excerpt, str):
        return None
    raw_sources = value.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = []
    kept = []
    for item in raw_sources:
        cleaned = clean_source_record(item)
        if cleaned is not None:
            kept.append(cleaned)
        if len(kept) >= MAX_SOURCES:
            break
    created = value.get("created", 0.0)
    if not isinstance(created, (int, float)) or isinstance(created, bool) \
            or not created >= 0:
        created = 0.0
    record: Dict[str, Any] = {
        "id": bid,
        "query": query.strip()[:MAX_BRIEF_QUERY_CHARS],
        "sources": kept,
        "excerpt": excerpt[:MAX_BRIEF_EXCERPT_CHARS],
        "created": float(created),
    }
    if is_valid_id(value.get("project_id")):
        record["project_id"] = value["project_id"]
    return record


def _clean_workflow_step(value: Any) -> Optional[Dict[str, Any]]:
    """Validate one pipeline step on the load path; None when malformed.

    Tool names keep bounded strings; args keep scalar values only
    (strings truncated) — dropping a non-scalar can only make the step
    fail safe at run time (a missing `confirm` denies, a missing query
    fails), never escalate it.
    """
    from services.limits import MAX_WORKFLOW_ARG_CHARS

    if not isinstance(value, dict):
        return None
    tool = value.get("tool", "")
    if not isinstance(tool, str) or not tool.strip():
        return None
    args = value.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None
    clean_args: Dict[str, Any] = {}
    for key, val in args.items():
        if not isinstance(key, str) or not key:
            return None
        if isinstance(val, str):
            clean_args[key] = val[:MAX_WORKFLOW_ARG_CHARS]
        elif isinstance(val, (int, float, bool)) or val is None:
            clean_args[key] = val
        # Non-scalars are dropped (fail safe — see docstring).
    return {"tool": tool.strip()[:MAX_TOOL_NAME_LEN], "args": clean_args}


def _clean_workflow_record(value: Any) -> Optional[Dict[str, Any]]:
    """Validate one saved pipeline; None when identity/steps fail.

    Strict on steps: a malformed step drops the WHOLE record (dropping
    single steps would renumber {{steps.N}} refs and silently change
    what the pipeline does). Records were validated at save time, so a
    drop here means on-disk corruption, never a user typo.
    """
    from services.limits import (
        MAX_WORKFLOW_DESC_CHARS,
        MAX_WORKFLOW_NAME_CHARS,
        MAX_WORKFLOW_STEPS,
    )

    if not isinstance(value, dict):
        return None
    wid = value.get("id")
    if not is_valid_id(wid):
        return None
    name = value.get("name", "")
    if not isinstance(name, str) or not name.strip():
        return None
    description = value.get("description", "")
    if not isinstance(description, str):
        description = ""
    raw_steps = value.get("steps", [])
    if not isinstance(raw_steps, list) or not raw_steps:
        return None
    if len(raw_steps) > MAX_WORKFLOW_STEPS:
        return None
    steps = []
    for entry in raw_steps:
        step = _clean_workflow_step(entry)
        if step is None:
            return None
        steps.append(step)
    if not steps:
        return None
    created = value.get("created", 0.0)
    if not isinstance(created, (int, float)) or isinstance(created, bool) \
            or not created >= 0:
        created = 0.0
    updated = value.get("updated", created)
    if not isinstance(updated, (int, float)) or isinstance(updated, bool) \
            or not updated >= 0:
        updated = float(created)
    return {
        "id": wid,
        "name": name.strip()[:MAX_WORKFLOW_NAME_CHARS],
        "description": description.strip()[:MAX_WORKFLOW_DESC_CHARS],
        "steps": steps,
        "created": float(created),
        "updated": float(updated),
    }


def _clean_project_record(value: Any) -> Optional[Dict[str, Any]]:
    """Validate one project record; None when identity-bearing fields fail.

    Bad id/name drops the record; bad created/archived coerce to safe
    defaults so one malformed entry never sinks the whole registry.
    """
    if not isinstance(value, dict):
        return None
    pid = value.get("id")
    name = value.get("name", "")
    if not is_valid_id(pid):
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    created = value.get("created", 0.0)
    if not isinstance(created, (int, float)) or not created >= 0:
        created = 0.0
    archived = value.get("archived", False)
    return {
        "id": pid,
        "name": name.strip()[:MAX_PROJECT_NAME_LEN],
        "created": float(created),
        "archived": archived is True,
    }
