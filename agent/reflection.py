"""Self-reflection: one critique pass over a draft answer, at most.

Reflection never restarts the main loop and never discards a good draft:
any reflection failure returns the draft unchanged.
"""

from typing import Optional, Sequence

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.budget import BudgetExhausted, RequestBudget
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.prompts import _as_text
from services.limits import (
    REFLECT_DRAFT_WINDOW_CHARS,
    REFLECT_FAILURE_KEYWORDS,
    REFLECT_MIN_IMPROVE_RATIO,
    REFLECT_SHORT_DRAFT_CHARS,
)

REFLECTION_ENABLED: bool = True


def should_reflect(
    task_type: str,
    draft_output: str,
    user_input: str,
    deep_mode: bool = False,
) -> bool:
    """Decide whether self-critique is worth an extra model call."""
    if not REFLECTION_ENABLED:
        return False
    if not deep_mode:
        return False
    if task_type == "simple":
        return False
    if task_type in ("creative", "multi_step"):
        return True
    if len(draft_output.strip()) < REFLECT_SHORT_DRAFT_CHARS:
        return True
    lowered = draft_output.lower()
    if any(kw in lowered for kw in REFLECT_FAILURE_KEYWORDS):
        return True
    return False


def _strip_fences(text: str) -> str:
    """Strip a leading ```lang ... ``` wrapper if present (return as-is otherwise)."""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        first = lines[0].strip()
        if first.startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _has_improve_marker(text: str) -> bool:
    """True when a reply line starts with the [IMPROVE] marker.

    Matched at line start (after stripping fences) so the model echoing
    the instructions verbatim cannot false-positive a pass.
    """
    body = _strip_fences(text or "").lstrip("`").strip()
    for line in body.splitlines():
        if line.lstrip().upper().startswith("[IMPROVE]"):
            return True
    return False


def _improved_text(text: str) -> str:
    """Extract the improved version after an anchored [IMPROVE] marker."""
    body = _strip_fences(text or "")
    for line in body.splitlines():
        if line.lstrip().upper().startswith("[IMPROVE]"):
            return line.split("]", 1)[1].strip() if "]" in line else ""
    return ""


def reflect_and_improve(
    llm_instance: BaseLanguageModel,
    original_input: str,
    draft_output: str,
    chat_history: Sequence[BaseMessage],
    budget: Optional[RequestBudget] = None,
) -> str:
    """Critique a draft answer; return the improved version or the draft.

    Never raises: any reflection failure returns the draft unchanged, so a
    good draft is never discarded because critique failed.
    """
    if not REFLECTION_ENABLED or not draft_output.strip():
        return draft_output
    if budget is not None:
        try:
            budget.count_reflect()
        except BudgetExhausted:
            return draft_output
    draft_window = (draft_output or "")[:REFLECT_DRAFT_WINDOW_CHARS]
    truncated = len(draft_output or "") > REFLECT_DRAFT_WINDOW_CHARS
    try:
        reflection_prompt = (
            "You just produced this output for the user. Critique it honestly: "
            "is it accurate, complete, well-structured?\n\n"
            f"Original request: {original_input}\n"
            f"Draft output:{' (first part shown; full text was truncated)' if truncated else ''}\n{draft_window}\n\n"
            "If the draft is good, reply with exactly: [PASS]\n"
            "If it needs improvement, reply with: [IMPROVE] followed by the "
            "full improved version. The rewrite must be at least as long and "
            "complete as the draft — never shorten it."
        )
        reflection = agent._invoke_bounded(
            llm_instance,
            [
                SystemMessage(
                    content="You are a critical editor. Be harsh but constructive."
                ),
                *chat_history,
                HumanMessage(content=reflection_prompt),
            ],
            budget=budget,
        )
        reflection_text = _as_text(reflection.content)
        if _has_improve_marker(reflection_text):
            improved = _improved_text(reflection_text)
            if not improved:
                return draft_output
            base_len = len((draft_output or "").strip())
            if base_len and len(improved) < base_len * REFLECT_MIN_IMPROVE_RATIO:
                # A substantially shorter rewrite is likely lossy — keep the draft.
                return draft_output
            return improved
        return draft_output
    except Exception:
        return draft_output
