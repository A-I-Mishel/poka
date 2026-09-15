"""Two-phase plan-then-execute handling for complex requests.

Writes a short plan first, then executes it with tools. Any planning
failure falls back to a plain tool loop instead of breaking the answer.
"""

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.budget import BudgetExhausted, RequestBudget
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.prompts import _as_text
from agent.toolrun import MAX_TOOL_ROUNDS, TOOL_MAP, _note_tier_failure, run_tool_loop
from services.limits import PLAN_MAX_CHARS


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
            on_progress, request_id,
        )

    if budget is not None:
        try:
            budget.count_plan()
        except BudgetExhausted:
            return _loop(user_input)
    try:
        tool_names = ", ".join(sorted(TOOL_MAP))
        plan_prompt = (
            "Given this user request, create a short step-by-step plan. "
            "Do NOT execute tools yet. You may plan around ONLY these tools: "
            f"{tool_names}\n\n"
            f"Request: {user_input}\nPlan:"
        )
        plan_response = agent._invoke_bounded(
            llm_instance,
            [
                SystemMessage(content="You are a planning assistant. Be concise."),
                *chat_history,
                HumanMessage(content=plan_prompt),
            ],
            budget=budget,
        )
        plan_text = _as_text(plan_response.content)
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
