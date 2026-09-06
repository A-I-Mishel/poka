"""Poka agent runtime: tiered LLM cascade with tools, memory, and budgets.

Package layout (dependency order: UI -> application -> agent -> services):

- agent.budget: one authoritative RequestBudget per request.
- agent.executor: shared bounded daemon pool + budget-charging invoke.
- agent.prompts: system prompt + memory isolated as untrusted data.
- agent.providers: cascade tier table (construction lives in config).
- agent.cascade: tier selection, cooldowns, fallback, error translation.
- agent.router: rule routing + LLM task classification.
- agent.toolrun: tool registry, single tool funnel, main tool loop.
- agent.planning / agent.reflection / agent.vision: optional stages.
- agent.runtime: request orchestration (answer_with_fallback).

This module re-exports the full pre-split surface so existing
importers (`import agent`, `from agent import ...`) keep working.
"""

from agent.budget import BudgetExhausted, RequestBudget
from agent.cascade import (
    ROUTER_STATS,
    SKIP_AFTER_FAILS,
    SKIP_SECONDS,
    SKIP_SECONDS_PERMANENT,
    _friendly_cascade_error,
    _ordered_tiers,
    _record_tier_failure,
    _record_tier_success,
    _run_cascade_step,
    _tier_skipped,
    _TIER_FAILS,
    _TIER_SKIP_UNTIL,
    _usable_tiers,
    classify_provider_error,
)
from agent.executor import (
    _BOUNDED_MAX_WORKERS,
    _bounded_pool,
    _BoundedExecutor,
    _call_bounded,
    _invoke_bounded,
)
from agent.planning import plan_then_execute
from agent.prompts import (
    _as_text,
    _build_system_prompt,
    _memory_data_block,
    _messages_to_langchain,
    _project_context_block,
    system_prompt,
)
from agent.providers import TIER_AGENT_GETTERS
from agent.reflection import REFLECTION_ENABLED, reflect_and_improve, should_reflect
from agent.router import (
    _GREETING_RE,
    _signals,
    _UPLOAD_ID_RE,
    classify_task,
    rule_route,
)
from agent.runtime import (
    AgentResult,
    answer_with_fallback,
    MAX_HISTORY_MESSAGES,
    probe_live_tier,
    summarize_history,
)
from agent.toolrun import (
    MAX_TOOL_ROUNDS,
    TOOL_MAP,
    _execute_tool_call,
    _run_tool_with_context,
    run_tool_loop,
    tools,
)
from agent.vision import _try_vision_answer

__all__ = [
    "AgentResult",
    "BudgetExhausted",
    "MAX_HISTORY_MESSAGES",
    "MAX_TOOL_ROUNDS",
    "REFLECTION_ENABLED",
    "ROUTER_STATS",
    "SKIP_AFTER_FAILS",
    "SKIP_SECONDS",
    "SKIP_SECONDS_PERMANENT",
    "TIER_AGENT_GETTERS",
    "TOOL_MAP",
    "RequestBudget",
    "_BOUNDED_MAX_WORKERS",
    "_GREETING_RE",
    "_TIER_FAILS",
    "_TIER_SKIP_UNTIL",
    "_UPLOAD_ID_RE",
    "_as_text",
    "_bounded_pool",
    "_BoundedExecutor",
    "_build_system_prompt",
    "_call_bounded",
    "_execute_tool_call",
    "_friendly_cascade_error",
    "_invoke_bounded",
    "_memory_data_block",
    "_messages_to_langchain",
    "_ordered_tiers",
    "_project_context_block",
    "_record_tier_failure",
    "_record_tier_success",
    "_run_cascade_step",
    "_run_tool_with_context",
    "_signals",
    "_tier_skipped",
    "_try_vision_answer",
    "_usable_tiers",
    "answer_with_fallback",
    "classify_provider_error",
    "classify_task",
    "plan_then_execute",
    "probe_live_tier",
    "reflect_and_improve",
    "rule_route",
    "run_tool_loop",
    "should_reflect",
    "summarize_history",
    "system_prompt",
    "tools",
]
