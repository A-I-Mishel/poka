"""Disk-persistent chat history and user memory notes for Poka.

Storage is plain local files (no extra services, no extra model calls):
- memory/chats.json : archived chats + the currently open chat
- memory/memory.md  : user-written notes Poka always keeps in context
"""

import json
import os
from typing import Any, Dict, List

MEMORY_DIR: str = "memory"
CHATS_PATH: str = os.path.join(MEMORY_DIR, "chats.json")
MEMORY_PATH: str = os.path.join(MEMORY_DIR, "memory.md")
MAX_STORED_CHATS: int = 20
MAX_MSGS_PER_CHAT: int = 100


def _ensure_dir() -> None:
    """Create the memory directory if missing."""
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _clean_messages(messages: Any) -> List[Dict[str, str]]:
    """Validate and trim a message list to plain role/content dicts."""
    cleaned: List[Dict[str, str]] = []
    if isinstance(messages, list):
        for m in messages:
            if (
                isinstance(m, dict)
                and m.get("role") in ("user", "assistant")
                and isinstance(m.get("content"), str)
            ):
                cleaned.append({"role": m["role"], "content": m["content"]})
    return cleaned[-MAX_MSGS_PER_CHAT:]


def load_store() -> Dict[str, Any]:
    """Load archived chats and the open chat from disk.

    Returns:
        Dict with 'chats' (list) and 'current' (message list). Empty
        defaults when nothing is stored yet or the file is corrupt.
    """
    try:
        with open(CHATS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"chats": [], "current": []}
        chats: List[Dict[str, Any]] = []
        raw_chats = data.get("chats", [])
        if isinstance(raw_chats, list):
            for c in raw_chats:
                if isinstance(c, dict):
                    chats.append(
                        {
                            "title": str(c.get("title", "Untitled"))[:60],
                            "messages": _clean_messages(c.get("messages", [])),
                        }
                    )
        return {
            "chats": chats[:MAX_STORED_CHATS],
            "current": _clean_messages(data.get("current", [])),
        }
    except (OSError, ValueError):
        return {"chats": [], "current": []}


def save_store(chats: Any, current: Any) -> None:
    """Persist archived chats and the open chat atomically.

    Args:
        chats: List of {"title": str, "messages": [...]} dicts.
        current: The currently open message list.
    """
    _ensure_dir()
    stored_chats: List[Dict[str, Any]] = []
    if isinstance(chats, list):
        for c in chats[:MAX_STORED_CHATS]:
            if isinstance(c, dict):
                stored_chats.append(
                    {
                        "title": str(c.get("title", "Untitled"))[:60],
                        "messages": _clean_messages(c.get("messages", [])),
                    }
                )
    payload: Dict[str, Any] = {
        "chats": stored_chats,
        "current": _clean_messages(current),
    }
    tmp_path: str = CHATS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp_path, CHATS_PATH)


def load_memory_notes() -> str:
    """Load the user's persistent memory notes (empty string if none)."""
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def save_memory_notes(text: str) -> None:
    """Save the user's persistent memory notes.

    Args:
        text: Free-form notes Poka should always remember.
    """
    _ensure_dir()
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        f.write(text)
