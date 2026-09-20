"""Self-reflection: one critique pass over a draft answer, at most.

Reflection never restarts the main loop and never discards a good draft:
any reflection failure returns the draft unchanged.
"""

from typing import Dict, Optional, Sequence

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.budget import BudgetExhausted, RequestBudget
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.prompts import _as_text
from services.limits import (
    REFLECT_DRAFT_WINDOW_CHARS,
    REFLECT_FAILURE_KEYWORDS,
    REFLECT_FAST_DRAFT_CHARS,
    REFLECT_MIN_IMPROVE_RATIO,
    REFLECT_SHORT_DRAFT_CHARS,
    MAX_QUERY_CHARS,
)

REFLECTION_ENABLED: bool = True

# Task-typed critique focus: one line per classifier task_type so the
# single critique pass checks what matters for THIS draft instead of
# generic quality. Coding lives under "data" (no separate "code" type).
_TASK_FOCUS: Dict[str, str] = {
    "research": "claims supported (never pass training knowledge off as fresh fact), complete, cited; for teaching answers also check source fidelity (only verified slides), concepts before terminology, and exam value",
    "creative": "structure, purpose-fit, consistent formatting",
    "data": "correct logic, edge cases, error handling, fits the surrounding project; no unsafe ops",
    "multi_step": "every requested step done, results consistent with each other; for teaching answers also check source fidelity (only verified slides) and recall checkpoints",
    "simple": "directly answers what was asked, nothing more",
}


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
        # Fast mode: substantial creative/research drafts earn one
        # cheap-tier critique (runs on CHEAP_TIERS, never the answer tier).
        # Research floor is lower (150): factual drafts benefit most.
        try:
            from services.limits import REFLECT_FAST_RESEARCH_CHARS as _RR
        except Exception:
            _RR = 150
        _len = len((draft_output or "").strip())
        if task_type == "research":
            return _len >= _RR
        return task_type == "creative" and _len >= REFLECT_FAST_DRAFT_CHARS
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
    """Extract the improved version after an anchored [IMPROVE] marker.

    Returns everything after the first [IMPROVE] marker (including newlines),
    not just the first line.
    """
    body = _strip_fences(text or "")
    for i, line in enumerate(body.splitlines()):
        if line.lstrip().upper().startswith("[IMPROVE]"):
            # Return everything after the marker on this line, plus all subsequent lines
            prefix = line.split("]", 1)[1] if "]" in line else ""
            rest = "\n".join(body.splitlines()[i+1:])
            combined = (prefix + "\n" + rest).strip()
            return combined
    return ""


def reflect_and_improve(
    llm_instance: BaseLanguageModel,
    original_input: str,
    draft_output: str,
    chat_history: Sequence[BaseMessage],
    budget: Optional[RequestBudget] = None,
    task_type: Optional[str] = None,
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
    # Cap original_input to prevent unbounded prompt growth
    capped_input = (original_input or "")[:MAX_QUERY_CHARS]
    focus = _TASK_FOCUS.get(str(task_type or "").strip().lower(),
                            "accurate, complete, well-structured")
    try:
        reflection_prompt = (
            "You just produced this output for the user. Critique it honestly: "
            f"is it {focus}?\n\n"
            f"Original request: {capped_input}\n"
            f"Draft output:{' (first part shown; full text was truncated)' if truncated else ''}\n{draft_window}\n\n"
            "If the draft is good, reply with exactly: [PASS]\n"
            "Reply [IMPROVE] (followed by the full improved version) ONLY when "
            "a requirement is wrong, missing, or unsafe — never for minor "
            "wording or style. The rewrite must be at least as long and "
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
            # Fail-closed: a weak critic may leak its deliberation
            # ("Critical assessment ..." table) into the rewrite — strip
            # any critique scaffold before accepting it. _strip never
            # raises; the outer handler covers the unexpected anyway.
            from agent.prompts import strip_internal_reasoning as _strip

            improved = _strip(improved)
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
