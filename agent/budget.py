"""Request budget management: one authoritative counter set per request.

Every LLM call, tool call, search, planning, and reflection step in a
request charges the same RequestBudget object, so retries, fallbacks,
and nested loops can never bypass or reset the limits. Budget
exhaustion raises BudgetExhausted, which the cascade propagates without
cooling providers (it is our limit, not theirs).
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from services.limits import (
    CONTEXT_MAX_TOKENS,
    MAX_LLM_CALLS_PER_REQUEST,
    MAX_PLANNING_CALLS,
    MAX_REFLECTION_CALLS,
    MAX_SEARCH_CALLS_PER_REQUEST,
    MAX_TOOL_CALLS_PER_REQUEST,
    MAX_TOOL_ROUNDS,
    MAX_TOTAL_REQUEST_TIME,
)


class BudgetExhausted(Exception):
    """Raised when a request-level budget runs out. Never marks tiers failed."""


logger = logging.getLogger(__name__)


class TurnCancelled(Exception):
    """Raised when the client went away mid-turn (stream disconnect).

    Never marks tiers failed, never triggers synthesis or salvage — there
    is nobody left to read an answer. Every layer must re-raise it
    untouched (it is not an error, not a budget event, not a fallback).
    """


def remaining_seconds(budget: Any) -> float:
    """Wall-clock seconds left on a budget's deadline (never raises).

    Returns inf for None (no deadline to honor). Same clock-domain rule
    as check_time: huge deadlines read as wall-clock, small ones as
    monotonic. Lets callers skip doomed long calls (synthesis retries)
    instead of burning provider quota against an expiring wall.
    """
    try:
        if budget is None:
            return float("inf")
        deadline = float(getattr(budget, "deadline", 0.0) or 0.0)
        if deadline <= 0.0:
            return float("inf")
        if deadline > 1e9:
            return deadline - time.time()
        return deadline - time.monotonic()
    except Exception:
        return float("inf")


@dataclass
class RequestBudget:
    """Bounded resources for one user message (also collects metrics).

    All mutating methods are thread-safe for parallel tool execution.
    """

    max_llm: int = MAX_LLM_CALLS_PER_REQUEST
    max_tools: int = MAX_TOOL_CALLS_PER_REQUEST
    max_search: int = MAX_SEARCH_CALLS_PER_REQUEST
    max_reflect: int = MAX_REFLECTION_CALLS
    max_plan: int = MAX_PLANNING_CALLS
    max_rounds: int = MAX_TOOL_ROUNDS
    deadline: float = field(default_factory=lambda: time.monotonic() + MAX_TOTAL_REQUEST_TIME)
    llm_calls: int = 0
    tool_calls: int = 0
    search_calls: int = 0
    reflect_calls: int = 0
    plan_calls: int = 0
    rounds: int = 0
    timeouts: int = 0
    external_tokens: int = 0
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    def check_time(self) -> None:
        """Raise BudgetExhausted when the request ran too long."""
        # Backwards compat: tests/tools may pass a wall-clock deadline
        # (time.time()-based, >1e9). Detect clock domain by magnitude.
        if self.deadline > 1e9:
            if time.time() > self.deadline:
                raise BudgetExhausted("Request time budget exhausted.")
        elif time.monotonic() > self.deadline:
            raise BudgetExhausted("Request time budget exhausted.")

    def count_llm(self) -> None:
        """Charge one model call; raise when the LLM budget is spent."""
        with self._lock:
            self.check_time()
            self.llm_calls += 1
            if self.llm_calls > self.max_llm:
                raise BudgetExhausted(f"LLM call budget exhausted ({self.max_llm}).")

    def count_tool(self, is_search: bool = False) -> None:
        """Charge one tool call (search calls have their own sub-budget)."""
        with self._lock:
            self.check_time()
            self.tool_calls += 1
            if is_search:
                self.search_calls += 1
                if self.search_calls > self.max_search:
                    raise BudgetExhausted(f"Search budget exhausted ({self.max_search}).")
            if self.tool_calls > self.max_tools:
                raise BudgetExhausted(f"Tool budget exhausted ({self.max_tools}).")

    def count_round(self) -> None:
        """Charge one tool-loop round; shared across nested loops.

        Lets Deep Mode chain past the per-loop round cap while one
        request-wide bound still holds. Callers treat exhaustion like
        loop end (synthesize from results), never as a hard error.
        """
        with self._lock:
            self.check_time()
            self.rounds += 1
            if self.rounds > self.max_rounds:
                raise BudgetExhausted(f"Tool round budget exhausted ({self.max_rounds}).")

    def count_reflect(self) -> None:
        """Charge one reflection call."""
        with self._lock:
            self.reflect_calls += 1
            if self.reflect_calls > self.max_reflect:
                raise BudgetExhausted(f"Reflection budget exhausted ({self.max_reflect}).")

    def count_plan(self) -> None:
        """Charge one planning call."""
        with self._lock:
            self.plan_calls += 1
            if self.plan_calls > self.max_plan:
                raise BudgetExhausted(f"Planning budget exhausted ({self.max_plan}).")

    def check_context(self, messages: Any) -> None:
        """Raise BudgetExhausted when prompt exceeds CONTEXT_MAX_TOKENS.

        Shape-tolerant, never crashes: str probes, single messages,
        dict/vision payloads and image blocks are skipped or counted as
        text only. Probes (plain str) are exempt — they carry no history.
        Uses services.context_budget._message_tokens + count_tokens so
        system_text is measured dynamically instead of the static
        CTX_SYSTEM_TOKENS=4000 estimate. Never cools tiers (our limit).
        """
        try:
            if messages is None or isinstance(messages, str):
                return
            from langchain_core.messages import BaseMessage as _BM
            from services.context_budget import _message_tokens as _mt
            if isinstance(messages, _BM):
                _msgs = [messages]
            elif isinstance(messages, (list, tuple)):
                _msgs = [m for m in messages if isinstance(m, _BM)]
                if not _msgs:
                    return
            else:
                return
            try:
                total = 0
                for m in _msgs:
                    try:
                        total += int(_mt(m))
                    except Exception:
                        logger.debug("context token probe failed; skipping message", exc_info=True)
                        continue
                    if total > int(CONTEXT_MAX_TOKENS):
                        break
            except Exception:
                return
            if total > int(CONTEXT_MAX_TOKENS):
                raise BudgetExhausted(
                    f"Context budget exhausted ({total}>{CONTEXT_MAX_TOKENS})."
                )
        except BudgetExhausted:
            raise
        except Exception:
            return
