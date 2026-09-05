"""Structured long-term memory with automatic extraction (no model calls).

Persists to structured_memory.json (gitignored user data):
- preferences: key/value likes and habits
- facts: extracted dated facts (name, preferences, task patterns)
- past_tasks: reserved for future task logging
- user_name: detected user name, if any
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List

MEMORY_FILE: str = "structured_memory.json"
MAX_FACTS: int = 50

# Optional override so hosts (e.g. per-user stores) can relocate the file.
# Defaults to the legacy working-directory location.
_MEMORY_DIR: str = ""


def set_memory_dir(directory: str) -> None:
    """Direct structured-memory reads/writes at directory/structured_memory.json."""
    global _MEMORY_DIR
    _MEMORY_DIR = directory or ""


def _memory_path() -> str:
    """Resolve the active structured-memory file path."""
    if _MEMORY_DIR:
        return os.path.join(_MEMORY_DIR, "structured_memory.json")
    return MEMORY_FILE


def _blank_memory() -> Dict[str, Any]:
    """Return an empty memory structure."""
    return {"preferences": {}, "facts": [], "past_tasks": [], "user_name": None}


def load_structured_memory() -> Dict[str, Any]:
    """Load memory from disk, or an empty structure when missing/corrupt."""
    try:
        with open(_memory_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _blank_memory()
        blank = _blank_memory()
        for key, default in blank.items():
            data.setdefault(key, default)
        if not isinstance(data.get("facts"), list):
            data["facts"] = []
        return data
    except (OSError, ValueError):
        return _blank_memory()


def save_structured_memory(mem: Dict[str, Any]) -> None:
    """Save memory to disk. Never raises (storage must not break chat)."""
    try:
        directory = os.path.dirname(_memory_path())
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(_memory_path(), "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def extract_facts_from_message(content: str) -> List[Dict[str, str]]:
    """Extract key facts from one message using regex heuristics.

    Args:
        content: A single user message.

    Returns:
        List of {"type": ..., "value": ...} fact dicts (may be empty).
    """
    facts: List[Dict[str, str]] = []
    if not content or not content.strip():
        return facts
    content_lower = content.lower()

    name_match = re.search(r"my name is (\w+)", content_lower)
    if name_match:
        facts.append({"type": "name", "value": name_match.group(1).title()})

    pref_patterns = [
        r"i (?:prefer|like|want|need) (.+)",
        r"my (?:favorite|preferred) (.+) is (.+)",
        r"always (?:use|set|make) (.+)",
    ]
    for pattern in pref_patterns:
        for match in re.finditer(pattern, content_lower):
            value = match.group(0).strip()
            if value:
                facts.append({"type": "preference", "value": value})

    if any(w in content_lower for w in ["presentation", "slides", "ppt"]):
        facts.append({"type": "task_pattern", "value": "frequently creates presentations"})
    if any(w in content_lower for w in ["email", "professor", "deadline"]):
        facts.append({"type": "task_pattern", "value": "frequently emails professors"})

    return facts


def update_memory_from_chat(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract facts from recent user messages and persist them (deduped).

    Args:
        messages: Raw chat message dicts with 'role'/'content'.

    Returns:
        The updated memory dict.
    """
    mem = load_structured_memory()
    if not isinstance(messages, list):
        return mem

    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        for fact in extract_facts_from_message(content):
            fact["date"] = datetime.now().isoformat()
            if fact["type"] == "name":
                mem["user_name"] = fact["value"]
            if not any(f.get("value") == fact["value"] for f in mem["facts"]):
                mem["facts"].append(fact)
                if len(mem["facts"]) > MAX_FACTS:
                    mem["facts"] = mem["facts"][-MAX_FACTS:]

    save_structured_memory(mem)
    return mem


def format_memory_for_prompt(mem: Dict[str, Any]) -> str:
    """Format stored memory into a concise prompt-ready string ("" when empty)."""
    lines: List[str] = []

    if mem.get("user_name"):
        lines.append(f"User name: {mem['user_name']}")

    prefs = [f["value"] for f in mem.get("facts", []) if f.get("type") == "preference"]
    if prefs:
        lines.append(f"User preferences: {'; '.join(prefs[-5:])}")

    patterns = [f["value"] for f in mem.get("facts", []) if f.get("type") == "task_pattern"]
    if patterns:
        unique = list(dict.fromkeys(patterns))[-3:]
        lines.append(f"Observed patterns: {'; '.join(unique)}")

    return "\n".join(lines)


def get_relevant_memory_context(user_input: str) -> str:
    """Return memory facts sharing keywords with the query ("" when none)."""
    mem = load_structured_memory()
    if not user_input or not user_input.strip():
        return ""
    input_words = set(user_input.lower().split())
    relevant: List[str] = []
    for fact in mem.get("facts", []):
        value = str(fact.get("value", ""))
        if set(value.lower().split()) & input_words:
            relevant.append(value)

    if relevant:
        return "Relevant context from past conversations:\n- " + "\n- ".join(relevant[:5])
    return ""
