"""Backward-compatible alias: the memory implementation lives in services.memory.

Canonical import for new code: `from services.memory import ...`.
This module re-exports the same objects so existing `import
memory_engine` sites keep working unchanged.
"""

from services.memory import (
    MAX_FACTS,
    MAX_PROCESSED_HASHES,
    MEMORY_FILE,
    _MEMORY_DIR,
    delete_memory_fact,
    extract_facts_from_message,
    format_memory_for_prompt,
    get_relevant_memory_context,
    list_memory_facts,
    load_structured_memory,
    save_structured_memory,
    set_memory_dir,
    update_memory_from_chat,
    update_memory_incremental,
)

__all__ = [
    "MAX_FACTS",
    "MAX_PROCESSED_HASHES",
    "MEMORY_FILE",
    "_MEMORY_DIR",
    "delete_memory_fact",
    "extract_facts_from_message",
    "format_memory_for_prompt",
    "get_relevant_memory_context",
    "list_memory_facts",
    "load_structured_memory",
    "save_structured_memory",
    "set_memory_dir",
    "update_memory_from_chat",
    "update_memory_incremental",
]
