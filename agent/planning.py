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
from agent.toolrun import MAX_TOOL_ROUNDS, run_tool_loop


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
) -> str:
    """Two-phase handling: write a plan first, then execute it with tools.

    Falls back to a plain tool loop if the planning call itself fails.
    Executed tool names and parsed search sources are appended to
    used_tools / used_sources when provided; project context flows
    into the execution loop's system prompt. When llm_provider is
    given, the execution loop fails over between tiers mid-task and
    records successful tiers into tier_trace.
    """
    def _loop(prompt: str) -> str:
        return run_tool_loop(
            llm_instance, prompt, chat_history, memory_notes,
            relevant_context, False, MAX_TOOL_ROUNDS, budget,
            used_tools, used_sources, project_context,
            llm_provider, tier_trace,
        )

    if budget is not None:
        try:
            budget.count_plan()
        except BudgetExhausted:
            return _loop(user_input)
    try:
        plan_prompt = (
            "Given this user request, create a short step-by-step plan. "
            "Do NOT execute tools yet. Output only the numbered plan.\n\n"
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
        execution_prompt = (
            f"Follow this plan to complete the request:\n{plan_text}\n\n"
            f"Original request: {user_input}\n\n"
            "Execute the plan using available tools. Adapt if tools fail."
        )
        return _loop(execution_prompt)
    except Exception:
        return _loop(user_input)
