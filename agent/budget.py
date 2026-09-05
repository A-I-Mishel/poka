"""Request budget management: one authoritative counter set per request.

Every LLM call, tool call, search, planning, and reflection step in a
request charges the same RequestBudget object, so retries, fallbacks,
and nested loops can never bypass or reset the limits. Budget
exhaustion raises BudgetExhausted, which the cascade propagates without
cooling providers (it is our limit, not theirs).
"""

import time
from dataclasses import dataclass, field

from services.limits import (
    MAX_LLM_CALLS_PER_REQUEST,
    MAX_PLANNING_CALLS,
    MAX_REFLECTION_CALLS,
    MAX_SEARCH_CALLS_PER_REQUEST,
    MAX_TOOL_CALLS_PER_REQUEST,
    MAX_TOTAL_REQUEST_TIME,
)


class BudgetExhausted(Exception):
    """Raised when a request-level budget runs out. Never marks tiers failed."""


@dataclass
class RequestBudget:
    """Bounded resources for one user message (also collects metrics)."""

    max_llm: int = MAX_LLM_CALLS_PER_REQUEST
    max_tools: int = MAX_TOOL_CALLS_PER_REQUEST
    max_search: int = MAX_SEARCH_CALLS_PER_REQUEST
    max_reflect: int = MAX_REFLECTION_CALLS
    max_plan: int = MAX_PLANNING_CALLS
    deadline: float = field(default_factory=lambda: time.time() + MAX_TOTAL_REQUEST_TIME)
    llm_calls: int = 0
    tool_calls: int = 0
    search_calls: int = 0
    reflect_calls: int = 0
    plan_calls: int = 0
    timeouts: int = 0
    external_tokens: int = 0

    def check_time(self) -> None:
        """Raise BudgetExhausted when the request ran too long."""
        if time.time() > self.deadline:
            raise BudgetExhausted("Request time budget exhausted.")

    def count_llm(self) -> None:
        """Charge one model call; raise when the LLM budget is spent."""
        self.check_time()
        self.llm_calls += 1
        if self.llm_calls > self.max_llm:
            raise BudgetExhausted(f"LLM call budget exhausted ({self.max_llm}).")

    def count_tool(self, is_search: bool = False) -> None:
        """Charge one tool call (search calls have their own sub-budget)."""
        self.check_time()
        self.tool_calls += 1
        if is_search:
            self.search_calls += 1
            if self.search_calls > self.max_search:
                raise BudgetExhausted(f"Search budget exhausted ({self.max_search}).")
        if self.tool_calls > self.max_tools:
            raise BudgetExhausted(f"Tool budget exhausted ({self.max_tools}).")

    def count_reflect(self) -> None:
        """Charge one reflection call."""
        self.reflect_calls += 1
        if self.reflect_calls > self.max_reflect:
            raise BudgetExhausted(f"Reflection budget exhausted ({self.max_reflect}).")

    def count_plan(self) -> None:
        """Charge one planning call."""
        self.plan_calls += 1
        if self.plan_calls > self.max_plan:
            raise BudgetExhausted(f"Planning budget exhausted ({self.max_plan}).")
