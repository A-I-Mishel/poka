"""Provider cascade: selection policy, cooldowns, error translation.

Single funnel for every tiered operation (classification, summarization,
planning, answering, reflection support, probing): a skipped provider is
never selected here. BudgetExhausted is never swallowed and never cools
a tier (it is our limit, not theirs).
"""

import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain_core.language_models.base import BaseLanguageModel

import agent  # package-attr routing: tier-table doubles on agent stay effective
from agent.budget import BudgetExhausted, TurnCancelled
from services.limits import (
    SLOW_TIER_LATENCY_SECONDS,
    TIER_COOLDOWN_CAPACITY_SECONDS,
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
# mean hours of darkness; capacity errors (bare outage, no quota
# evidence) mean minutes; auth/invalid config never heals by retrying.
SKIP_AFTER_FAILS: int = 1
_TIER_FAILS: Dict[str, int] = {}
_TIER_TIMEOUTS: Dict[str, int] = {}
_TIER_SKIP_UNTIL: Dict[str, float] = {}

# Tiers that cannot take tools-bound calls (local VL models served over
# an OpenAI-compatible endpoint). Tool rounds skip them without a
# network call, and a "does not support tools" 400 classifies as
# capability (recorded for honest footers, never cooled: it is a
# permanent capability, not an outage — cooling it would also block
# its tool-free vision use for an hour).
NO_TOOLS_TIERS = ("Ollama VL 3B",)

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

logger = logging.getLogger(__name__)


def _friendly_reason(kind: str) -> str:
    """Short user-facing reason for a tier failure kind (every tier)."""
    return {
        "rate_limit": "rate-limited",
        "timeout": "timed out",
        "auth": "unavailable (auth)",
        "invalid": "unavailable (rejected)",
        "capability": "does not support tools",
        "server": "temporarily unavailable",
        "capacity": "capacity-limited",
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
    # Google JSON bodies carry the delay instead of (or as well as) the
    # header: {"error": {..., "details": [{"retryDelay": "49s"}]}}.
    try:
        for match in re.finditer(r'"retryDelay"\s*:\s*"?(\d+(?:\.\d+)?)\s*s?"?', str(error or "")):
            try:
                parsed = float(match.group(1))
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
    except Exception:
        logger.debug("retryDelay body parse failed", exc_info=True)
    return None


# Structured provider reason tokens, matched against flattened error
# text (non-alphanumerics stripped, lowercased) so camelCase, SNAKE,
# and quoted-JSON variants all hit uniformly. Quota reasons prove
# quota exhaustion; capacity reasons prove outage WITHOUT quota
# evidence. "overloaded" is capacity-only corroboration here: Google
# emits it on both 429s (which already carry quota language) and bare
# 503s (which must not inherit a 6-hour quota ban).
_QUOTA_REASONS = (
    "ratelimitexceeded",
    "quotaexceeded",
    "resourceexhausted",
)
_CAPACITY_REASONS = (
    "serviceunavailable",
    "overloaded",
)


def _provider_reason(error: Any) -> str:
    """Structured failure reason from provider payloads (never raises).

    Returns "quota", "capacity", or "". Quota language anywhere in the
    payload wins over capacity language (a 503 body quoting quota is
    quota exhaustion, not an outage).
    """
    try:
        flat = re.sub(r"[^a-z0-9]", "", str(error or "").lower())
        if not flat:
            return ""
        if any(token in flat for token in _QUOTA_REASONS):
            return "quota"
        if any(token in flat for token in _CAPACITY_REASONS):
            return "capacity"
        return ""
    except Exception:
        return ""


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
    # No-tools capability (local VL models over OpenAI-compatible
    # endpoints): a tools-bound call 400s, but the tier is healthy for
    # tool-free calls (direct answers, vision). Must precede the
    # 400/invalid branch below — same gateway-400 pattern as above —
    # or one tool round would ban the tier (and its vision use) for an
    # hour.
    if "does not support tools" in lowered:
        return ("capability", True)
    # Structured provider evidence first: a quota or capacity reason in
    # the payload outranks substring guessing (a 503 body quoting quota
    # is quota exhaustion; "overloaded" alone is outage, never quota).
    # Prefer parsed int status; use \b-bounded regex for text fallbacks so
    # "1400"/"4000" don't misclassify as 400 (1h invalid cooldown).
    reason = _provider_reason(error)
    if (
        status == 429
        or reason == "quota"
        or re.search(r"\b429\b", text) is not None
        or "quota" in lowered
        or "rate limit" in lowered
        or "freeusagelimit" in lowered
        or "resource_exhausted" in lowered
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
        reason == "capacity"
        or status == 503
        or re.search(r"\b503\b", text) is not None
    ):
        # Bare service-unavailable / capacity outage WITHOUT quota
        # evidence: intermediate path, never the 6-hour quota ban.
        return ("capacity", True)
    if (
        status in (500, 502, 504)
        or re.search(r"\b500\b", text) is not None
        or re.search(r"\b502\b", text) is not None
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


def _is_shed_load(error: Any) -> bool:
    """Our limit, not theirs: saturated pool must never cool a tier."""
    return type(error).__name__ == "ExecutorBusyError"


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


def _provider_delay(window: float, error: Any = None) -> float:
    """Provider-supplied delay when shorter than the window, else the window.

    Covers Retry-After headers and retryDelay JSON bodies (parsed by
    _retry_after_seconds): a provider asking for 2 minutes beats both
    the 6-hour quota blanket and the 30-minute capacity blanket.
    """
    try:
        retry_after = _retry_after_seconds(error)
        if retry_after is not None and 0 < retry_after < window:
            return retry_after
    except Exception:
        logger.debug("provider delay parse failed", exc_info=True)
    return window


def _cooldown_for_kind(kind: str, error: Any = None) -> float:
    """Cool-down window for one classify_provider_error kind.

    Rate-limit windows prefer the provider's own delay when it is
    shorter than the blanket quota cool-down, so a 60s-per-provider 429
    recovers the tier in a minute instead of hours. Capacity windows do
    the same against the shorter capacity blanket.
    """
    if kind == "timeout":
        return TIER_COOLDOWN_TIMEOUT_SECONDS
    if kind == "rate_limit":
        return _provider_delay(TIER_COOLDOWN_QUOTA_SECONDS, error)
    if kind == "capacity":
        return _provider_delay(TIER_COOLDOWN_CAPACITY_SECONDS, error)
    if kind in ("auth", "invalid"):
        return TIER_COOLDOWN_PERMANENT_SECONDS
    return TIER_COOLDOWN_TRANSIENT_SECONDS


def _redact_detail(detail: str) -> str:
    """Strip key/token fragments from provider text (never logs secrets)."""
    try:
        text = str(detail or "")
        # sk-..., Bearer xxx, key=xxx, token xxx, account ids
        text = re.sub(r"\bsk-[A-Za-z0-9-_]{4,}\b", "sk-***", text)
        text = re.sub(r"(?i)\b(bearer|api[_-]?key|token|secret|password)\b\s*[:=]\s*\S+", r"\1=***", text)
        text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "***@***", text)
        return text[:200]
    except Exception:
        return ""


def _record_tier_failure(name: str, kind: str = "unknown", error: Any = None) -> None:
    """Count a failure; cool the tier down for its kind's window.

    Timeouts are congestion, not outage: the first consecutive timeout
    is a free pass (the tier stays live), the Nth consecutive one cools
    briefly. Any success or non-timeout failure resets the streak.
    The latest failure (kind + redacted detail) is always remembered
    in _TIER_LAST_ERROR — even timeout free passes — so fallbacks can
    be explained for any tier.
    """
    with _STATE_LOCK:
        try:
            if isinstance(name, str) and name:
                raw = str(error)[:500] if error is not None else kind
                _TIER_LAST_ERROR[name] = (kind, _redact_detail(raw), time.time())
        except Exception:
            logger.debug("tier last-error record failed", exc_info=True)
        if kind == "capability":
            # Not an outage: the tier is healthy for tool-free calls.
            # Never cool, never count — a tools 400 must not ban the
            # tier's vision use for an hour.
            return
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
    raw: str = _redact_detail(str(last_error))
    lowered: str = raw.lower()
    if re.search(r"\b429\b", raw) is not None or "quota" in lowered or "rate limit" in lowered or "freeusagelimit" in lowered \
            or "usage limit" in lowered or "usagelimit" in lowered:
        return (
            "All model tiers are unavailable right now: the free services are "
            "rate-limited (daily quotas reset tomorrow) or temporarily down. "
            "Please wait a while and try again."
        )
    return "All LLM tiers failed at runtime. Please try again in a moment."


def _ordered_tiers(
    first: Optional[str],
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]],
) -> List[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]:
    """Order tiers with the preferred (last working) tier first."""
    ordered = list(tiers) if tiers is not None else list(agent.TIER_AGENT_GETTERS)
    if first:
        ordered.sort(key=lambda item: 0 if item[0] == first else 1)
    return ordered


# Per-tier successful-call latency EMA (seconds) for slow-tier demotion.
# _LAT_EMA_ALPHA controls how fast one sample moves the average; cold
# tiers (no samples) sort normally so new providers are never penalized.
_TIER_LAT_EMA: Dict[str, float] = {}
_LAT_EMA_ALPHA: float = 0.3


def _record_latency(name: str, seconds: float) -> None:
    """Fold one successful call latency into the tier EMA. Never raises."""
    try:
        if not isinstance(name, str) or not name:
            return
        secs = float(seconds)
        if not 0 < secs < 600:
            return
        with _STATE_LOCK:
            prev = _TIER_LAT_EMA.get(name)
            _TIER_LAT_EMA[name] = secs if prev is None else (
                _LAT_EMA_ALPHA * secs + (1.0 - _LAT_EMA_ALPHA) * prev)
    except Exception:
        logger.debug("tier latency EMA update failed", exc_info=True)


def _is_slow_tier(name: str) -> bool:
    """True when the tier's latency EMA exceeds the demotion threshold."""
    try:
        with _STATE_LOCK:
            ema = _TIER_LAT_EMA.get(name)
        return ema is not None and ema > float(SLOW_TIER_LATENCY_SECONDS)
    except Exception:
        return False


def _usable_tiers(
    first: Optional[str] = None,
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]] = None,
    prefer_fast: bool = False,
) -> List[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]:
    """Central tier policy: preferred order minus cooled-down providers.

    Hammer fallback when all cooled: returning [] would deadlock the
    request until a window expires, while retrying lets a recovered
    provider answer immediately (transient vs quota cooldowns still
    recorded). Fail-fast for quota (6h) is handled by callers via
    friendly error after one hammer attempt. With prefer_fast, tiers
    whose latency EMA exceeds SLOW_TIER_LATENCY_SECONDS sort last
    (stable partition — relative order otherwise preserved, and slow
    tiers are demoted, never excluded).
    """
    ordered = _ordered_tiers(first, tiers)
    usable = [item for item in ordered if not _tier_skipped(item[0])]
    picked = usable or ordered
    if prefer_fast:
        try:
            slow = [item for item in picked if _is_slow_tier(item[0])]
            if slow and len(slow) < len(picked):
                fast = [item for item in picked if not _is_slow_tier(item[0])]
                return fast + slow
        except Exception:
            logger.debug("slow-tier demotion failed; using cascade order", exc_info=True)
    return picked


def tier_status_snapshot(
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]] = None,
) -> List[Dict[str, Any]]:
    """Point-in-time tier health for ops (never raises, metadata only).

    Per tier: configured (getter resolves), skipped + seconds remaining,
    fail/timeout streaks, last error kind/detail (truncated at record
    time). No     prompts, keys, or user data.
    """
    snapshot: List[Dict[str, Any]] = []
    try:
        table = list(tiers) if tiers is not None else list(agent.TIER_AGENT_GETTERS)
    except Exception:
        return snapshot
    now = time.time()
    for name, getter in table:
        entry: Dict[str, Any] = {"name": name}
        try:
            entry["configured"] = getter() is not None
        except Exception:
            entry["configured"] = False
        try:
            with _STATE_LOCK:
                skip_until = float(_TIER_SKIP_UNTIL.get(name, 0.0) or 0.0)
                fails = int(_TIER_FAILS.get(name, 0) or 0)
                timeouts = int(_TIER_TIMEOUTS.get(name, 0) or 0)
                last = _TIER_LAST_ERROR.get(name)
            entry["skipped"] = now < skip_until
            entry["cooldown_remaining_s"] = round(max(0.0, skip_until - now), 1)
            entry["fail_streak"] = fails
            entry["timeout_streak"] = timeouts
            if last is not None:
                entry["last_error_kind"] = str(last[0])
                entry["last_error"] = _redact_detail(str(last[1]))[:200]
        except Exception:
            logger.debug("tier snapshot entry failed", exc_info=True)
        snapshot.append(entry)
    return snapshot


def reset_tier_state(name: Optional[str] = None) -> int:
    """Clear cooldown/failure state for one tier (or all). Returns count cleared.

    Ops escape hatch for fat-fingered keys causing hours-long "permanent"
    cooldowns: fix the key, force-reset, traffic resumes immediately.
    """
    cleared = 0
    try:
        with _STATE_LOCK:
            targets = [name] if name else (
                list(_TIER_SKIP_UNTIL) + list(_TIER_FAILS)
                + list(_TIER_TIMEOUTS) + list(_TIER_LAST_ERROR)
                + list(_TIER_LAT_EMA)
            )
            for tier_name in dict.fromkeys(t for t in targets if t):
                for store in (_TIER_SKIP_UNTIL, _TIER_FAILS,
                              _TIER_TIMEOUTS, _TIER_LAST_ERROR,
                              _TIER_LAT_EMA):
                    if store.pop(tier_name, None) is not None:
                        cleared += 1
    except Exception:
        logger.debug("tier state reset failed", exc_info=True)
    return cleared


def _all_skipped_permanent(
    tiers: Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]],
) -> bool:
    """True when every tier is cooled for quota/auth/invalid (hammer would burn quota).

    Capacity outages stay hammer-capable by design: they recover in
    minutes, and the capacity cool-down itself (not this gate) is what
    stops outage-night hammering — a recovered tier answers immediately
    on expiry instead of waiting out a quota-scale ban.
    """
    for name, _ in tiers:
        if not _tier_skipped(name):
            return False
        hit = last_tier_error(name)
        if hit is None or hit[0] not in ("rate_limit", "auth", "invalid"):
            return False
    return bool(tiers)


def _run_cascade_step(
    fn: Callable[[str, BaseLanguageModel], Any],
    first: Optional[str] = None,
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]] = None,
    attempts: Optional[List[str]] = None,
    prefer_fast: bool = False,
) -> Tuple[str, Any]:
    """Run fn(name, llm) on tiers under ONE policy. Returns (tier, result).

    This is the single funnel for classification, summarization, planning,
    answering, reflection support, and probing: a skipped provider is never
    selected here, no matter which feature is calling. BudgetExhausted and
    ExecutorBusyError are never swallowed and never cool a tier (they are
    our limits, not theirs). Tried tier names are appended to `attempts`
    when provided (metrics). prefer_fast demotes high-latency-EMA tiers
    for interactive answers (they still answer if everything else fails).
    """
    ordered = _ordered_tiers(first, tiers)
    if ordered and _all_skipped_permanent(ordered):
        last_kind, last_detail = last_tier_error(ordered[0][0]) or ("rate_limit", "")
        raise RuntimeError(_friendly_cascade_error(f"{last_kind}: {last_detail}"))
    last_error: Exception | None = None
    first_attempt: Optional[str] = None
    for name, getter in _usable_tiers(first, tiers, prefer_fast):
        if attempts is not None:
            attempts.append(name)
        if first_attempt is None:
            first_attempt = name
        try:
            llm_instance = getter()
        except BudgetExhausted:
            raise
        except Exception as e:
            last_error = e
            if _is_shed_load(e):
                raise
            _record_tier_failure(name, classify_provider_error(e)[0], e)
            try:
                from services.obs import record_tier_fallback as _fb

                _fb(first_attempt or name, name, classify_provider_error(e)[0])
            except Exception:
                logger.debug("tier fallback metric failed", exc_info=True)
            continue
        if llm_instance is None:
            continue
        try:
            result = fn(name, llm_instance)
            _record_tier_success(name)
            if first_attempt is not None and name != first_attempt:
                try:
                    from services.obs import record_tier_fallback as _fb2

                    _fb2(first_attempt, name, "fallback")
                except Exception:
                    logger.debug("tier fallback metric failed", exc_info=True)
            return name, result
        except BudgetExhausted:
            raise
        except TurnCancelled:
            # Client went away: propagate untouched — never cool the tier,
            # never convert into a fallback. There is nobody to answer to.
            raise
        except Exception as e:
            last_error = e
            if _is_shed_load(e):
                raise
            _record_tier_failure(name, classify_provider_error(e)[0], e)
            try:
                from services.obs import record_tier_fallback as _fb3

                _fb3(first_attempt or name, name, classify_provider_error(e)[0])
            except Exception:
                logger.debug("tier fallback metric failed", exc_info=True)
            continue
    raise RuntimeError(_friendly_cascade_error(last_error))
