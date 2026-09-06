"""Project resource derivation (Phase 5D).

Conversation membership (project_id on archived chats) is the single
direct project relationship. Files, artifacts, and sources are DERIVED
views over member conversations — never copied, never re-owned, never
given their own project_id.

All helpers here are pure (no Streamlit, no filesystem): callers pass
in-memory chats/messages and resolve IDs through the existing
ownership-aware stores. Missing/malformed references are skipped, so
pruned files, expired artifacts, and tampered records degrade to
absence instead of errors.
"""

from typing import Any, Dict, List, Optional

from services.storage import clean_source_record
from services.limits import MAX_DISPLAY_NAME_CHARS

#: Display cap for the project Sources section (deduped, first-seen).
MAX_PROJECT_SOURCES: int = 10


def project_bucket(chat: Any, valid_ids: Any) -> Any:
    """Bucket for one conversation: project id or None (Personal).

    Only an id resolving to an existing ACTIVE project counts; absent,
    malformed, orphan, or archived ids all behave as Personal. Never
    rewrites the record.
    """
    pid = chat.get("project_id") if isinstance(chat, dict) else None
    if isinstance(pid, str) and isinstance(valid_ids, set) and pid in valid_ids:
        return pid
    return None


def member_conversations(chats: Any, bucket: Any, valid_ids: Any) -> List[Dict[str, Any]]:
    """Archived conversations belonging to one bucket, in stored order."""
    if not isinstance(chats, list):
        return []
    return [
        c for c in chats
        if isinstance(c, dict) and project_bucket(c, valid_ids) == bucket
    ]


def messages_of(convos: Any) -> List[Dict[str, Any]]:
    """Flatten message dicts from conversation records, in order."""
    out: List[Dict[str, Any]] = []
    if not isinstance(convos, list):
        return out
    for convo in convos:
        if not isinstance(convo, dict):
            continue
        messages = convo.get("messages", [])
        if not isinstance(messages, list):
            continue
        out.extend(m for m in messages if isinstance(m, dict))
    return out


def upload_ids_in(messages: Any) -> List[str]:
    """Ordered unique upload IDs from message attachments[]."""
    found: List[str] = []
    if not isinstance(messages, list):
        return found
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        attachments = msg.get("attachments", [])
        if not isinstance(attachments, list):
            continue
        for att in attachments:
            if not isinstance(att, dict):
                continue
            uid = att.get("id", "")
            if isinstance(uid, str) and uid and uid not in found:
                found.append(uid)
    return found


def artifact_entries_in(messages: Any) -> List[Dict[str, str]]:
    """Ordered unique artifact links ({id,kind,name}) from messages."""
    found: List[Dict[str, str]] = []
    seen = set()
    if not isinstance(messages, list):
        return found
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        links = msg.get("artifacts", [])
        if not isinstance(links, list):
            continue
        for entry in links:
            if not isinstance(entry, dict):
                continue
            file_id = entry.get("id", "")
            kind = entry.get("kind", "")
            name = entry.get("name", "")
            if (not isinstance(file_id, str) or not file_id
                    or file_id in seen):
                continue
            if kind not in ("pptx", "docx", "file"):
                continue
            if not isinstance(name, str) or not name:
                continue
            seen.add(file_id)
            found.append({"id": file_id, "kind": kind, "name": name[:MAX_DISPLAY_NAME_CHARS]})
    return found


def source_entries_in(messages: Any) -> List[Dict[str, str]]:
    """Validated deduped source records from assistant messages.

    Only structured sources[] metadata is read — model markdown is
    never parsed. Deduplicated by lowercased URL, first-seen order.
    """
    found: List[Dict[str, str]] = []
    seen_urls = set()
    if not isinstance(messages, list):
        return found
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        stored = msg.get("sources", [])
        if not isinstance(stored, list):
            continue
        for entry in stored:
            record = clean_source_record(entry)
            if record is None:
                continue
            key = record["url"].lower()
            if key in seen_urls:
                continue
            seen_urls.add(key)
            found.append(record)
    return found


def open_bucket(open_project_id: Any, valid_ids: Any) -> Any:
    """Bucket for the open (unarchived) conversation, same rule as stored."""
    if (isinstance(open_project_id, str) and isinstance(valid_ids, set)
            and open_project_id in valid_ids):
        return open_project_id
    return None
