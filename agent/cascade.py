"""Provider cascade: selection policy, cooldowns, error translation.

Single funnel for every tiered operation (classification, summarization,
planning, answering, reflection support, probing): a skipped provider is
never selected here. BudgetExhausted is never swallowed and never cools
a tier (it is our limit, not theirs).
"""

import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain_core.language_models.base import BaseLanguageModel

import agent  # package-attr routing: tier-table doubles on agent stay effective
from agent.budget import BudgetExhausted
from services.limits import (
    TIER_COOLDOWN_PERMANENT_SECONDS,
    TIER_COOLDOWN_QUOTA_SECONDS,
    TIER_COOLDOWN_TIMEOUT_SECONDS,
    TIER_COOLDOWN_TRANSIENT_SECONDS,
    TIMEOUT_STRIKES_BEFORE_COOL,
)

# Skip a failing tier so the next message goes straight to the next
# live model (cool-down still expires so recovered tiers return).
# Cool-down length is driven by the classify_provider_error kind:
# timeouts are congestion (brief, 2nd consecutive strike); quota errors
# mean hours of darkness; auth/invalid config never heals by retrying.
SKIP_AFTER_FAILS: int = 1
SKIP_SECONDS: float = TIER_COOLDOWN_TRANSIENT_SECONDS
SKIP_SECONDS_PERMANENT: float = TIER_COOLDOWN_PERMANENT_SECONDS
_TIER_FAILS: Dict[str, int] = {}
_TIER_TIMEOUTS: Dict[str, int] = {}
_TIER_SKIP_UNTIL: Dict[str, float] = {}

# Last failure per tier: (kind, truncated detail, timestamp). Lets callers
# explain a fallback ("Big Pickle rate-limited") for ANY tier without
# changing cascade signatures. Bounded (one entry per known tier) and
# metadata-only (truncated like _friendly_cascade_error, never prompts).
_TIER_LAST_ERROR: Dict[str, tuple] = {}

# Concurrency: tier state is shared across the bounded daemon pool, so
# every read-modify-write on the _TIER_* dicts goes through ONE lock
# (mirrors services.ratelimit). Misses here are benign (two callers
# cooling the same tier) but serializing keeps streak counting exact.
_STATE_LOCK = threading.Lock()


def _friendly_reason(kind: str) -> str:
    """Short user-facing reason for a tier failure kind (every tier)."""
    return {
        "rate_limit": "rate-limited",
        "timeout": "timed out",
        "auth": "unavailable (auth)",
        "invalid": "unavailable (rejected)",
        "server": "temporarily unavailable",
        "network": "unreachable",
    }.get(kind, "temporarily unavailable")


def last_tier_error(name: str) -> Optional[tuple]:
    """Return (kind, detail) of a tier's most recent failure, or None."""
    if not isinstance(name, str) or not name:
        return None
    with _STATE_LOCK:
        hit = _TIER_LAST_ERROR.get(name)
        if hit is None:
            return None
        kind, detail, _ = hit
    return kind, detail

# Deterministic router stats (process-aggregate metrics, no user data).
ROUTER_STATS: Dict[str, int] = {"rule": 0, "llm": 0}


def _http_status(error: Any) -> Optional[int]:
    """Best-effort HTTP status code from a provider exception."""
    if error is None:
        return None
    for attr in ("status_code", "status"):
        code = getattr(error, attr, None)
        if isinstance(code, int):
            return code
        if code is not None:
            try:
                parsed = int(code)
                return parsed
            except (TypeError, ValueError):
                pass
    resp = getattr(error, "response", None)
    code = getattr(resp, "status_code", None) if resp is not None else None
    return code if isinstance(code, int) else None


def _retry_after_seconds(error: Any) -> Optional[float]:
    """Best-effort Retry-After seconds from a provider 429 (headers)."""
    if error is None:
        return None
    candidates: List[Any] = []
    resp = getattr(error, "response", None)
    if resp is not None:
        headers = getattr(resp, "headers", None)
        if headers is not None and hasattr(headers, "get"):
            candidates.append(headers.get("Retry-After"))
            candidates.append(headers.get("retry-after"))
    hdrs = getattr(error, "headers", None)
    if hdrs is not None and hasattr(hdrs, "get"):
        candidates.append(hdrs.get("Retry-After"))
        candidates.append(hdrs.get("retry-after"))
    for raw in candidates:
        if raw is None:
            continue
        try:
            parsed = float(str(raw).strip())
            if parsed > 0:
                return parsed
        except (TypeError, ValueError):
            continue
    return None


def classify_provider_error(error: Any) -> Tuple[str, bool]:
    """Classify a provider failure as (kind, retryable_elsewhere).

    Permanent kinds (bad credentials, invalid requests) earn a long
    cool-down; temporary ones keep the short cool-down. Budget exhaustion
    is ours, never the provider's — callers must handle it separately.
    """
    text = str(error)
    lowered = text.lower()
    status = _http_status(error)
    if isinstance(error, TimeoutError) or status == 408 or "timed out after" in lowered:
        return ("timeout", True)
    # Encrypted-reasoning replay (Anthropic encrypted_content /
    # thought_signature via a gateway): a stale payload issue, not a
    # broken tier. Sanitize-on-send (executor) prevents it; if one still
    # slips through, fail over fast with a transient cool-down instead
    # of the hour-long "invalid" ban. Must precede the 400/invalid
    # branch below since gateways report it as HTTP 400.
    if (
        "encrypted_content" in lowered
        or "thought_signature" in lowered
        or "not issued to this caller" in lowered
        or ("reasoning" in lowered and "signature" in lowered)
    ):
        return ("unknown", True)
    # Prefer parsed int status; use \b-bounded regex for text fallbacks so
    # "1400"/"4000" don't misclassify as 400 (1h invalid cooldown).
    if (
        status == 429
        or re.search(r"\b429\b", text) is not None
        or "quota" in lowered
        or "rate limit" in lowered
        or "freeusagelimit" in lowered
        or "resource_exhausted" in lowered
        or "overloaded" in lowered
        or "usage limit" in lowered
        or "usagelimit" in lowered
        or re.search(r"\b529\b", text) is not None
    ):
        return ("rate_limit", True)
    if (
        status in (401, 403)
        or re.search(r"\b401\b", text) is not None
        or re.search(r"\b403\b", text) is not None
        or "unauthorized" in lowered
        or "invalid api key" in lowered
        or "invalid_api_key" in lowered
        or "credits" in lowered
        or "permission denied" in lowered
    ):
        return ("auth", False)
    if (
        status in (500, 502, 503, 504)
        or re.search(r"\b500\b", text) is not None
        or re.search(r"\b502\b", text) is not None
        or re.search(r"\b503\b", text) is not None
        or re.search(r"\b504\b", text) is not None
        or "internal" in lowered
        or "unavailable" in lowered
    ):
        return ("server", True)
    if (
        status in (400, 404, 422)
        or re.search(r"\b400\b", text) is not None
        or re.search(r"\b404\b", text) is not None
        or re.search(r"\b422\b", text) is not None
        or "invalid" in lowered
        or "bad request" in lowered
    ):
        return ("invalid", False)
    if isinstance(error, ConnectionError) or "connection" in lowered or "network" in lowered or "dns" in lowered:
        return ("network", True)
    return ("unknown", True)


def _tier_skipped(name: str) -> bool:
    """Check whether a tier is currently in its cool-down window."""
    with _STATE_LOCK:
        return time.time() < _TIER_SKIP_UNTIL.get(name, 0.0)


def _record_tier_success(name: str) -> None:
    """Clear failure state after a tier answers successfully."""
    with _STATE_LOCK:
        _TIER_FAILS.pop(name, None)
        _TIER_TIMEOUTS.pop(name, None)
        _TIER_SKIP_UNTIL.pop(name, None)


def _cooldown_for_kind(kind: str, error: Any = None) -> float:
    """Cool-down window for one classify_provider_error kind.

    Rate-limit windows prefer the provider's own Retry-After when it is
    shorter than the blanket quota cool-down, so a 60s-per-provider 429
    recovers the tier in a minute instead of hours.
    """
    if kind == "timeout":
        return TIER_COOLDOWN_TIMEOUT_SECONDS
    if kind == "rate_limit":
        window: float = TIER_COOLDOWN_QUOTA_SECONDS
        retry_after = _retry_after_seconds(error)
        if retry_after is not None and 0 < retry_after < window:
            return retry_after
        return window
    if kind in ("auth", "invalid"):
        return TIER_COOLDOWN_PERMANENT_SECONDS
    return TIER_COOLDOWN_TRANSIENT_SECONDS


def _record_tier_failure(name: str, kind: str = "unknown", error: Any = None) -> None:
    """Count a failure; cool the tier down for its kind's window.

    Timeouts are congestion, not outage: the first consecutive timeout
    is a free pass (the tier stays live), the Nth consecutive one cools
    briefly. Any success or non-timeout failure resets the streak.
    The latest failure (kind + truncated detail) is always remembered
    in _TIER_LAST_ERROR — even timeout free passes — so fallbacks can
    be explained for any tier.
    """
    with _STATE_LOCK:
        try:
            if isinstance(name, str) and name:
                detail = str(error)[:200] if error is not None else kind
                _TIER_LAST_ERROR[name] = (kind, detail, time.time())
        except Exception:
            pass
        if kind == "timeout":
            streak: int = _TIER_TIMEOUTS.get(name, 0) + 1
            _TIER_TIMEOUTS[name] = streak
            if streak >= TIMEOUT_STRIKES_BEFORE_COOL:
                _TIER_SKIP_UNTIL[name] = time.time() + TIER_COOLDOWN_TIMEOUT_SECONDS
            return
        _TIER_TIMEOUTS.pop(name, None)
        fails: int = _TIER_FAILS.get(name, 0) + 1
        _TIER_FAILS[name] = fails
        if fails >= SKIP_AFTER_FAILS:
            _TIER_SKIP_UNTIL[name] = time.time() + _cooldown_for_kind(kind, error)


def _friendly_cascade_error(last_error: Any) -> str:
    """Translate raw provider errors into a human-readable message."""
    raw: str = str(last_error)
    lowered: str = raw.lower()
    if "429" in raw or "quota" in lowered or "rate limit" in lowered or "freeusagelimit" in lowered \
            or "usage limit" in lowered or "usagelimit" in lowered:
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
    """Central tier policy: preferred order minus cooled-down providers.

    Hammer fallback when all cooled: returning [] would deadlock the
    request until a window expires, while retrying lets a recovered
    provider answer immediately (transient vs quota cooldowns still
    recorded). Fail-fast for quota (6h) is handled by callers via
    friendly error after one hammer attempt.
    """
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
            _record_tier_failure(name, classify_provider_error(e)[0], e)
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
            _record_tier_failure(name, classify_provider_error(e)[0], e)
            continue
    raise RuntimeError(_friendly_cascade_error(last_error))


async def _run_cascade_step_async(
    fn: Callable[[str, BaseLanguageModel], Any],
    first: Optional[str] = None,
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]] = None,
    attempts: Optional[List[str]] = None,
    max_concurrent: int = 3,
) -> Tuple[str, Any]:
    """Run fn(name, llm) on tiers CONcurrently, returning first success.

    Tries all usable tiers in parallel (up to max_concurrent at a time),
    cancels remaining on first success. Preserves attempt order for metrics.
    Falls back to serial on BudgetExhausted or when no tiers usable.
    """
    import asyncio

    usable = _usable_tiers(first, tiers)
    if not usable:
        raise RuntimeError("No usable tiers available")

    last_error: Exception | None = None

    # If only one tier, run directly (avoid executor overhead)
    if len(usable) == 1:
        name, getter = usable[0]
        if attempts is not None:
            attempts.append(name)
        try:
            llm_instance = getter()
        except BudgetExhausted:
            raise
        except Exception as e:
            last_error = e
            _record_tier_failure(name, classify_provider_error(e)[0], e)
            raise RuntimeError(_friendly_cascade_error(last_error))
        if llm_instance is None:
            raise RuntimeError("Tier returned None LLM")
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, lambda: fn(name, llm_instance))
            _record_tier_success(name)
            return name, result
        except BudgetExhausted:
            raise
        except Exception as e:
            _record_tier_failure(name, classify_provider_error(e)[0], e)
            raise RuntimeError(_friendly_cascade_error(e))

    # Multiple tiers: race them with limited concurrency
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = {}

    async def _try_tier(name: str, getter: Callable[[], Optional[BaseLanguageModel]]) -> Tuple[str, Any]:
        nonlocal last_error
        async with semaphore:
            if attempts is not None:
                attempts.append(name)
            try:
                # Get LLM instance (may block on I/O)
                llm_instance = await asyncio.get_event_loop().run_in_executor(None, getter)
            except BudgetExhausted:
                raise
            except Exception as e:
                last_error = e
                _record_tier_failure(name, classify_provider_error(e)[0], e)
                raise
            if llm_instance is None:
                raise RuntimeError(f"Tier {name} returned None LLM")
            try:
                result = await asyncio.get_event_loop().run_in_executor(None, lambda: fn(name, llm_instance))
                _record_tier_success(name)
                return name, result
            except BudgetExhausted:
                raise
            except Exception as e:
                _record_tier_failure(name, classify_provider_error(e)[0], e)
                raise

    # Create tasks for all usable tiers
    for name, getter in usable:
        tasks[name] = asyncio.create_task(_try_tier(name, getter))

    # Wait for first completion
    while tasks:
        done, pending = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            try:
                result = task.result()
                # Cancel remaining tasks
                for p in pending:
                    p.cancel()
                # Wait for cancellation to complete
                if pending:
                    await asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED)
                return result
            except BudgetExhausted:
                # Cancel all and re-raise
                for p in pending:
                    p.cancel()
                raise
            except Exception as e:
                last_error = e
                # This tier failed, continue with remaining
                pass
        # Remove completed task
        for name, task in list(tasks.items()):
            if task in done:
                del tasks[name]

    # All tiers failed
    raise RuntimeError(_friendly_cascade_error(last_error))
