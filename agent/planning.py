"""Two-phase plan-then-execute handling for complex requests.

Writes a short plan first, then executes it with tools. Any planning
failure falls back to a plain tool loop instead of breaking the answer.
"""

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.budget import RequestBudget
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.prompts import _as_text
from agent.toolrun import MAX_TOOL_ROUNDS, TOOL_MAP, _note_tier_failure, run_tool_loop
from services.limits import PLAN_MAX_CHARS

logger = logging.getLogger(__name__)


# Argument/identifier names that merely look like tools (never flagged).
_PLAN_NON_TOOL_WORDS = frozenset({
    "upload_id", "file_id", "chat_id", "message_id", "project_id",
    "draft_id", "artifact_id", "event_id", "tool_call", "tool_calls",
    "max_results", "limit_key", "user_id", "request_id", "tool_name",
})
_PLAN_TOOL_VERBS = ("use", "using", "call", "calls", "calling", "invoke",
                    "invokes", "run", "runs", "via", "tool", "with")
_PLAN_SNAKE_RE = re.compile(r"`([a-z][a-z0-9_]{2,})`|\b([a-z][a-z0-9_]{2,})\b")


def _unknown_plan_tools(plan_text: str) -> List[str]:
    """Snake_case tokens in a plan that are not real tools (never raises).

    Only tokens in backticks or near tool verbs (use/call/run/via/with)
    are candidates, so prose like variable names and argument IDs rarely
    trip it; known ID-ish words are allowlisted. Returns unknowns in
    first-seen order.
    """
    try:
        words = str(plan_text or "").lower().split()
        found: List[str] = []
        seen: set = set()
        for i, raw in enumerate(words):
            m = _PLAN_SNAKE_RE.search(raw)
            if not m:
                continue
            token = (m.group(1) or m.group(2) or "").strip("_")
            if not token or "_" not in token or token in TOOL_MAP:
                continue
            if token in _PLAN_NON_TOOL_WORDS or token in seen:
                continue
            window = " ".join(words[max(0, i - 3):i])
            quoted = raw.strip().startswith("`")
            verbed = re.search(
                r"\b(" + "|".join(_PLAN_TOOL_VERBS) + r")\b", window) is not None
            if quoted or verbed:
                seen.add(token)
                found.append(token)
        return found
    except Exception:
        return []


def plan_then_execute(
    llm_instance: BaseLanguageModel,
    user_input: str,
    chat_history: Sequence[BaseMessage],
    memory_notes: str = "",
    relevant_context: str = "",
    budget: Optional[RequestBudget] = None,
    used_tools: Optional[List[str]] = None,
    used_sources: Optional[List[Dict[str, str]]] = None,
    project_context: str = "",
    llm_provider: Optional[Callable[[], Tuple[str, Any]]] = None,
    tier_trace: Optional[List[str]] = None,
    on_token: Optional[Callable[[str], None]] = None,
    on_reset: Optional[Callable[[], None]] = None,
    final_tier: Optional[List[str]] = None,
    max_rounds: int = MAX_TOOL_ROUNDS,
    on_progress: Optional[Callable[[str], None]] = None,
    attempt_tier: Optional[str] = None,
    failed_tiers: Optional[set] = None,
    request_id: Optional[str] = None,
    cheap_tiers: Optional[Sequence] = None,
    cancel: Optional[Callable[[], bool]] = None,
    strict: bool = False,
) -> str:
    """Two-phase handling: write a plan first, then execute it with tools.

    Falls back to a plain tool loop if the planning call itself fails.
    Executed tool names and parsed search sources are appended to
    used_tools / used_sources when provided; project context flows
    into the execution loop's system prompt. When llm_provider is
    given, the execution loop fails over between tiers mid-task and
    records successful tiers into tier_trace. When attempt_tier names
    this cascade attempt's tier, a failed planning call cools it down
    and records it into failed_tiers (when given) so execution
    continues on the next live tier instead of retrying the dead one
    first — no collected work is lost (planning produced none) and the
    turn is never restarted from scratch.
    """
    def _loop(prompt: str) -> str:
        return run_tool_loop(
            llm_instance, prompt, chat_history, memory_notes,
            relevant_context, False, max_rounds, budget,
            used_tools, used_sources, project_context,
            llm_provider, tier_trace, on_token, on_reset, final_tier,
            on_progress, request_id, cancel, strict,
        )

    if budget is not None:
        budget.count_plan()

    def _ask_plan(p_llm: BaseLanguageModel, prompt: str) -> str:
        plan_response = agent._invoke_bounded(
            p_llm,
            [
                SystemMessage(content="You are a planning assistant. Be concise."),
                *chat_history,
                HumanMessage(content=prompt),
            ],
            budget=budget,
        )
        return _as_text(plan_response.content)

    def _ask_plan_default(prompt: str) -> str:
        # Dumb call: cheap tiers first, attempt tier as fallback. Cheap
        # failures must not implicate the attempt tier (it never ran);
        # quota exhaustion falls through to the legacy path below,
        # preserving its exact semantics.
        if cheap_tiers is not None:
            from agent.cascade import _run_cascade_step as _cascade

            try:
                _, text = _cascade(
                    lambda _n, _llm: _ask_plan(_llm, prompt), None, cheap_tiers)
                return text
            except Exception:
                logger.debug("cheap-tier planning failed; using attempt tier", exc_info=True)
        return _ask_plan(llm_instance, prompt)

    try:
        tool_names = ", ".join(sorted(TOOL_MAP))
        plan_prompt = (
            "Given this user request, create a short step-by-step plan. "
            "Do NOT execute tools yet.\n"
            "Shape your plan exactly like this:\n"
            "Goal: <one line: what success looks like>\n"
            "Steps:\n"
            "1. <step> — tool: <one tool from the list below>\n"
            "2. ...\n"
            "Expected output: <shape of the final answer>\n"
            "You may plan around ONLY these tools: "
            f"{tool_names}\n\n"
            "Example:\n"
            "Goal: report average age from the CSV\n"
            "Steps:\n"
            "1. Inspect columns — tool: analyze_csv\n"
            "Expected output: one sentence with the average.\n\n"
            f"Request: {user_input}\nPlan:"
        )
        plan_text = _ask_plan_default(plan_prompt)
        unknown = _unknown_plan_tools(plan_text)
        if unknown:
            # One bounded replan naming only real tools, then proceed
            # regardless — a second failure still executes (never loops).
            correction = (
                f"{plan_prompt}\n\nCorrection: '{unknown[0]}' is not an "
                f"available tool. Use ONLY these tools: {tool_names}\nPlan:")
            try:
                plan_text = _ask_plan_default(correction)
            except Exception:
                logger.debug("bounded plan replan failed; executing anyway", exc_info=True)
        # Bounded before injection into the execution prompt: a runaway
        # plan must not crowd the context budget.
        plan_text = plan_text[:PLAN_MAX_CHARS]
        execution_prompt = (
            f"Follow this plan to complete the request:\n{plan_text}\n\n"
            f"Original request: {user_input}\n\n"
            "Execute the plan using available tools. Adapt if tools fail."
        )
        return _loop(execution_prompt)
    except Exception as e:
        # The planning call ran on this attempt's tier: cool it and mark
        # it failed so the execution loop's provider skips the dead tier
        # and continues on the next live one (unknown/empty names are
        # ignored by _note_tier_failure; a missing set simply skips).
        _note_tier_failure(attempt_tier, e)
        if failed_tiers is not None and isinstance(attempt_tier, str) and attempt_tier:
            failed_tiers.add(attempt_tier)
        return _loop(user_input)
