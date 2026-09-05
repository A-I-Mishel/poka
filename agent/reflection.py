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
    if len(draft_output.strip()) < 80:
        return True
    lowered = draft_output.lower()
    if any(kw in lowered for kw in ["error", "failed", "unable to", "could not"]):
        return True
    return False


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
    try:
        reflection_prompt = (
            "You just produced this output for the user. Critique it honestly: "
            "is it accurate, complete, well-structured?\n\n"
            f"Original request: {original_input}\n"
            f"Draft output: {draft_output}\n\n"
            "If the draft is good, reply with exactly: [PASS]\n"
            "If it needs improvement, reply with: [IMPROVE] followed by the "
            "full improved version."
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
        if "[IMPROVE]" in reflection_text:
            improved = reflection_text.split("[IMPROVE]", 1)[1].strip()
            return improved if improved else draft_output
        return draft_output
    except Exception:
        return draft_output
