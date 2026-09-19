"""Chat turn orchestration: send/regenerate entry points.

Package split of the former `backend/flow.py` monolith — one submodule
per concern (`stages`, `teaching`, `turns`). Every name the old module
exposed is re-exported here, so `from backend.flow import X` and
`backend.chatflow` keep working unchanged.
"""

from backend.flow.stages import (
    _assistant_meta,
    _attachment_classifier,
    _available_for_gate,
    _check_limits,
    _clean_sources,
    _fallback_info,
    _load_state,
    _memory_and_project,
    _turn_approvals,
    build_chat_history,
)
from backend.flow.teaching import _apply_teaching_session
from backend.flow.turns import (
    EPISODIC_MIN_MESSAGES,
    EPISODIC_SUMMARY_CHARS,
    _apply_attachment_gate,
    _complete_turn,
    _complete_turn_guarded,
    archive_current,
    maybe_attach_episodic_summary,
    regenerate_chat,
    run_chat,
)

__all__ = [
    "EPISODIC_MIN_MESSAGES",
    "EPISODIC_SUMMARY_CHARS",
    "_apply_attachment_gate",
    "_apply_teaching_session",
    "_assistant_meta",
    "_attachment_classifier",
    "_available_for_gate",
    "_check_limits",
    "_clean_sources",
    "_complete_turn",
    "_complete_turn_guarded",
    "_fallback_info",
    "_load_state",
    "_memory_and_project",
    "_turn_approvals",
    "archive_current",
    "build_chat_history",
    "maybe_attach_episodic_summary",
    "regenerate_chat",
    "run_chat",
]
