"""Provider cascade: selection policy, cooldowns, error translation.

Single funnel for every tiered operation (classification, summarization,
planning, answering, reflection support, probing): a skipped provider is
never selected here. BudgetExhausted is never swallowed and never cools
a tier (it is our limit, not theirs).
"""

import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain_core.language_models.base import BaseLanguageModel

import agent  # package-attr routing: tier-table doubles on agent stay effective
from agent.budget import BudgetExhausted

# Skip a failing tier immediately so the next message goes straight to
# the next live model (cool-down still expires so recovered tiers return).
# Permanent failures (bad credentials, invalid requests) cool down longer.
SKIP_AFTER_FAILS: int = 1
SKIP_SECONDS: float = 600.0
SKIP_SECONDS_PERMANENT: float = 3600.0
_TIER_FAILS: Dict[str, int] = {}
_TIER_SKIP_UNTIL: Dict[str, float] = {}

# Deterministic router stats (process-aggregate metrics, no user data).
ROUTER_STATS: Dict[str, int] = {"rule": 0, "llm": 0}


def classify_provider_error(error: Any) -> Tuple[str, bool]:
    """Classify a provider failure as (kind, retryable_elsewhere).

    Permanent kinds (bad credentials, invalid requests) earn a long
    cool-down; temporary ones keep the short cool-down. Budget exhaustion
    is ours, never the provider's — callers must handle it separately.
    """
    text = str(error)
    lowered = text.lower()
    if isinstance(error, TimeoutError) or "timed out after" in lowered:
        return ("timeout", True)
    if (
        "429" in text
        or "quota" in lowered
        or "rate limit" in lowered
        or "freeusagelimit" in lowered
        or "resource_exhausted" in lowered
        or "overloaded" in lowered
        or "529" in text
    ):
        return ("rate_limit", True)
    if (
        "401" in text
        or "403" in text
        or "unauthorized" in lowered
        or "invalid api key" in lowered
        or "invalid_api_key" in lowered
        or "credits" in lowered
        or "permission denied" in lowered
    ):
        return ("auth", False)
    if (
        "500" in text
        or "502" in text
        or "503" in text
        or "504" in text
        or "internal" in lowered
        or "unavailable" in lowered
    ):
        return ("server", True)
    if "400" in text or "invalid" in lowered or "bad request" in lowered:
        return ("invalid", False)
    if isinstance(error, ConnectionError) or "connection" in lowered or "network" in lowered or "dns" in lowered:
        return ("network", True)
    return ("unknown", True)


def _tier_skipped(name: str) -> bool:
    """Check whether a tier is currently in its cool-down window."""
    return time.time() < _TIER_SKIP_UNTIL.get(name, 0.0)


def _record_tier_success(name: str) -> None:
    """Clear failure state after a tier answers successfully."""
    _TIER_FAILS.pop(name, None)
    _TIER_SKIP_UNTIL.pop(name, None)


def _record_tier_failure(name: str, permanent: bool = False) -> None:
    """Count a failure; cool the tier down (longer when permanent)."""
    fails: int = _TIER_FAILS.get(name, 0) + 1
    _TIER_FAILS[name] = fails
    window = SKIP_SECONDS_PERMANENT if permanent else SKIP_SECONDS
    if fails >= SKIP_AFTER_FAILS:
        _TIER_SKIP_UNTIL[name] = time.time() + window


def _friendly_cascade_error(last_error: Any) -> str:
    """Translate raw provider errors into a human-readable message."""
    raw: str = str(last_error)
    lowered: str = raw.lower()
    if "429" in raw or "quota" in lowered or "rate limit" in lowered or "freeusagelimit" in lowered:
        return (
            "All model tiers are unavailable right now: the free services are "
            "rate-limited (daily quotas reset tomorrow) or temporarily down. "
            "Please wait a while and try again. "
            f"Technical detail: {raw[:200]}"
        )
    return f"All LLM tiers failed at runtime. Last error: {raw[:300]}"


def _ordered_tiers(
    first: Optional[str],
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]],
) -> List[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]:
    """Order tiers with the preferred (last working) tier first."""
    ordered = list(tiers) if tiers is not None else list(agent.TIER_AGENT_GETTERS)
    if first:
        ordered.sort(key=lambda item: 0 if item[0] == first else 1)
    return ordered


def _usable_tiers(
    first: Optional[str] = None,
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]] = None,
) -> List[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]:
    """Central tier policy: preferred order minus cooled-down providers."""
    ordered = _ordered_tiers(first, tiers)
    usable = [item for item in ordered if not _tier_skipped(item[0])]
    return usable or ordered


def _run_cascade_step(
    fn: Callable[[str, BaseLanguageModel], Any],
    first: Optional[str] = None,
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]] = None,
    attempts: Optional[List[str]] = None,
) -> Tuple[str, Any]:
    """Run fn(name, llm) on tiers under ONE policy. Returns (tier, result).

    This is the single funnel for classification, summarization, planning,
    answering, reflection support, and probing: a skipped provider is never
    selected here, no matter which feature is calling. BudgetExhausted is
    never swallowed and never cools a tier (it is our limit, not theirs).
    Tried tier names are appended to `attempts` when provided (metrics).
    """
    last_error: Exception | None = None
    for name, getter in _usable_tiers(first, tiers):
        if attempts is not None:
            attempts.append(name)
        try:
            llm_instance = getter()
        except BudgetExhausted:
            raise
        except Exception as e:
            last_error = e
            _, permanent = classify_provider_error(e)
            _record_tier_failure(name, permanent)
            continue
        if llm_instance is None:
            continue
        try:
            result = fn(name, llm_instance)
            _record_tier_success(name)
            return name, result
        except BudgetExhausted:
            raise
        except Exception as e:
            last_error = e
            _, permanent = classify_provider_error(e)
            _record_tier_failure(name, permanent)
            continue
    raise RuntimeError(_friendly_cascade_error(last_error))
