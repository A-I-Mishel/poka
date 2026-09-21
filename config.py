"""Multi-tier LLM cascade: Gemini (main) -> Groq -> emergency fallbacks.

Cascade order (user preference): Gemini 3.8 / 3.7 / 3.6 Flash (main,
same GEMINI_API_KEY) + 3.5 backup -> Groq 120B (strong fallback) ->
Groq Fast 20B (fast/simple, cheap-only) -> Cohere -> Nemotron 3 Ultra
-> OpenRouter Free Router -> Mistral (last resort). GitHub Models +
NVIDIA removed (dead). Other curated OpenRouter lanes removed; only
Nemotron Ultra (user pick) + openrouter/free kept.

OpenCode Zen free tier retired Sep 2026: provider returns
MissingSessionID ("free tier can only be used in OpenCode") for
API calls, so the 6 free lanes were removed. Paid Zen models remain
usable via the same base URL if billing is added.
"""

import hashlib
import secrets
import threading
from typing import Any, Callable, Dict, Optional, Tuple, Union
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from services.limits import MODEL_MAX_TOKENS, MODEL_TIMEOUT_SECONDS
from services.secrets import get_secret

import os as _os

if _os.getenv("PLUTO_DOTENV", "1").strip().lower() not in ("0", "false", "no", "off"):
    load_dotenv(override=False)

GEMINI_38_MODEL: str = "gemini-3.8-flash"
GEMINI_37_MODEL: str = "gemini-3.7-flash"
GEMINI_36_MODEL: str = "gemini-3.6-flash"
GEMINI_35_MODEL: str = "gemini-3.5-flash"
# OpenCode Zen free tier retired Sep 2026 (MissingSessionID for API
# calls). 6 free lanes removed: muse-spark-1.3-contributor-free,
# nemotron-3.5-lightning-free, nemotron-3-ultra-free, big-pickle,
# mimo-v2.5-free, ling-3.0-flash-fin-free. Paid Zen models remain
# usable via https://opencode.ai/zen/v1 if billing is added.
# Groq via its OpenAI-compatible endpoint (no extra dependency needed).
# Two lanes share one GROQ_API_KEY: Groq = 120B strong fallback,
# Groq Fast = 20B fast/simple (cheap-only, never final answers).
# Llama models were retired from Groq in Aug 2026. Override with
# GROQ_MODEL (120B) / GROQ_FAST_MODEL (20B) if needed.
GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
GROQ_MODEL: str = "openai/gpt-oss-120b"
GROQ_FAST_MODEL: str = "openai/gpt-oss-20b"
# Cerebras retired Sep 2026: free tier now returns payment_required
# (quota/billing gate) for gpt-oss-120b — removed from cascade.
# Re-add via https://api.cerebras.ai/v1 if billing is added.
# GitHub Models + NVIDIA removed (dead, not working anymore).
# Mistral La Plateforme via its OpenAI-compatible endpoint.
# No-card free evaluation tier (rate-limited, prototyping-grade);
# open-weight default keeps the free lane usable.
MISTRAL_BASE_URL: str = "https://api.mistral.ai/v1"
MISTRAL_MODEL: str = "open-mistral-nemo"
# Cohere via its OpenAI-compatible endpoint (same ChatOpenAI client).
# Direct API key from dashboard.cohere.com; Command A default is
# synthesis-grade, so this lane is a full cascade member (not cheap-only).
COHERE_BASE_URL: str = "https://api.cohere.com/compatibility/v1"
COHERE_MODEL: str = "command-a-03-2025"
# OpenRouter via its OpenAI-compatible endpoint (same ChatOpenAI client).
# Emergency pool: one curated strong lane (Nemotron 3 Ultra, user pick)
# ahead of the Free Router fallback. Other curated free-model lanes
# (Gemma/Super/3.5/26B/Ling-Fin/Laguna) stay removed — promos rotate,
# router auto-selects live free models.
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_ULTRA_MODEL: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
# OpenRouter Free Model Router (released Feb 2026): selects a free model
# at random from the live catalog, smartly filtering for features the
# request needs (tool calling, image understanding, structured output).
OPENROUTER_FREE_ROUTER_MODEL: str = "openrouter/free"
TEMPERATURE: float = 0.7

# Client cache: clients hold only model config + credentials (no user
# data, prompts, or memories), so sharing them process-wide is safe and
# avoids paying construction (~60ms OpenAI, ~700ms Gemini) on every tier
# use. Keyed by (tier, temperature); the active key is re-checked on
# every lookup so rotation takes effect promptly. Only a hash of the key
# is retained for that comparison, never the key itself beyond what the
# client object requires. Bounded keyspace (tiers x task temperatures)
# plus a hard cap; instances are never mutated after caching (callers
# needing another temperature fetch their own entry via get_tier_llm).
_CLIENT_CACHE: Dict[Tuple[str, float, str], Tuple[str, Any]] = {}
_CLIENT_CACHE_LOCK = threading.Lock()
_MAX_CACHED_CLIENTS: int = 32


def _key_fingerprint(key: str) -> str:
    """Non-reversible identity for cache rotation checks (never logged)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _cached_client(tier: str, temperature: float, key: str, model: str, make: Callable[[], Any]) -> Any:
    """Return the cached client for (tier, temperature, key, model), building once."""
    cache_key = (tier, float(temperature), str(model))
    fingerprint = _key_fingerprint(f"{key}\x00{model}")
    with _CLIENT_CACHE_LOCK:
        hit = _CLIENT_CACHE.get(cache_key)
        if hit is not None and secrets.compare_digest(hit[0], fingerprint):
            return hit[1]
    client = make()
    with _CLIENT_CACHE_LOCK:
        if len(_CLIENT_CACHE) >= _MAX_CACHED_CLIENTS:
            # Evict oldest instead of nuking all hot clients (Gemini ~700ms each).
            try:
                _CLIENT_CACHE.pop(next(iter(_CLIENT_CACHE)))
            except (StopIteration, KeyError):
                pass
        _CLIENT_CACHE[cache_key] = (fingerprint, client)
    return client


def _clear_client_cache() -> None:
    """Clear cached LLM clients (tests; prevents test-key poisoning)."""
    with _CLIENT_CACHE_LOCK:
        _CLIENT_CACHE.clear()


def _get_secret(name: str) -> Optional[str]:
    """Read a secret from env/.env.

    Thin wrapper over the central services.secrets seam (kept for
    backward compatibility).

    Args:
        name: Secret name, e.g. "GEMINI_API_KEY".

    Returns:
        The secret value, or None if not set anywhere.
    """
    return get_secret(name)


# OpenCode Zen free lanes removed Sep 2026: provider returns
# MissingSessionID ("free tier can only be used in OpenCode") for API
# calls. Paid Zen models can be re-added here via the same base URL
# (https://opencode.ai/zen/v1) when billing is added.


def _make_gemini(model: str, key: str, temperature: float):
    """Build ChatGoogleGenerativeAI across langchain-google-genai versions.

    Older releases accept convert_system_message_to_human; newer ones
    (4.x, consolidated google-genai SDK) deprecated/removed it.
    request_timeout is kept on every attempt: it is the native HTTP
    timeout that truly aborts hung provider calls.
    max_retries=0 everywhere: SDK-level tenacity retries (2s/4s/8s...
    backoff per attempt) multiply free-tier quota burn — the daily
    allowance is ~20 requests — and add minutes before the cascade can
    fail over. The cascade IS the retry mechanism (across tiers, with
    cooldowns); one attempt per call fails fast into it.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI

    base = dict(
        model=model,
        api_key=key,  # type: ignore[arg-type]
        temperature=temperature,
        request_timeout=MODEL_TIMEOUT_SECONDS,
        max_output_tokens=MODEL_MAX_TOKENS,
        max_retries=0,
    )
    try:
        return ChatGoogleGenerativeAI(
            **base,  # type: ignore[arg-type]
            convert_system_message_to_human=True,  # type: ignore[call-arg]
        )
    except TypeError:
        try:
            return ChatGoogleGenerativeAI(**base)  # type: ignore[arg-type]
        except TypeError:
            # Ancient releases without max_retries: retry storm accepted,
            # cascade still bounds the damage via timeouts + cooldowns.
            base.pop("max_retries", None)
            return ChatGoogleGenerativeAI(**base)  # type: ignore[arg-type]


def get_tier_gemini38_llm(temperature: float = TEMPERATURE) -> Optional[ChatGoogleGenerativeAI]:
    """Main: Gemini 3.8 Flash -- newest, first try."""
    key: Optional[str] = _get_secret("GEMINI_API_KEY")
    if key is None:
        return None
    try:
        return _cached_client(
            "Gemini 3.8 Flash", temperature, key, GEMINI_38_MODEL,
            lambda: _make_gemini(_model_override("GEMINI_38_MODEL", GEMINI_38_MODEL), key, temperature),
        )
    except Exception:
        return None


def get_tier_gemini37_llm(temperature: float = TEMPERATURE) -> Optional[ChatGoogleGenerativeAI]:
    """Main: Gemini 3.7 Flash -- second try."""
    key: Optional[str] = _get_secret("GEMINI_API_KEY")
    if key is None:
        return None
    try:
        return _cached_client(
            "Gemini 3.7 Flash", temperature, key, GEMINI_37_MODEL,
            lambda: _make_gemini(_model_override("GEMINI_37_MODEL", GEMINI_37_MODEL), key, temperature),
        )
    except Exception:
        return None


def get_tier2_llm(temperature: float = TEMPERATURE) -> Optional[ChatGoogleGenerativeAI]:
    """Main: Gemini 3.6 Flash -- third try (legacy name kept)."""
    key: Optional[str] = _get_secret("GEMINI_API_KEY")
    if key is None:
        return None
    try:
        return _cached_client(
            "Gemini 3.6 Flash", temperature, key, GEMINI_36_MODEL,
            lambda: _make_gemini(_model_override("GEMINI_36_MODEL", GEMINI_36_MODEL), key, temperature),
        )
    except Exception:
        return None


def get_tier3_llm(temperature: float = TEMPERATURE) -> Optional[ChatGoogleGenerativeAI]:
    """Backup: Gemini 3.5 Flash -- fourth Gemini (legacy name kept)."""
    key: Optional[str] = _get_secret("GEMINI_API_KEY")
    if key is None:
        return None
    try:
        return _cached_client(
            "Gemini 3.5 Flash", temperature, key, GEMINI_35_MODEL,
            lambda: _make_gemini(_model_override("GEMINI_35_MODEL", GEMINI_35_MODEL), key, temperature),
        )
    except Exception:
        return None


def _groq_model() -> str:
    """Groq model ID, overridable via GROQ_MODEL env/secret."""
    try:
        override = _get_secret("GROQ_MODEL")
    except Exception:
        override = None
    if override and override.strip():
        return override.strip()
    return GROQ_MODEL


def get_tier_groq_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """Groq 120B: strong fallback via LPU inference (OpenAI-compatible)."""
    key: Optional[str] = _get_secret("GROQ_API_KEY")
    if key is None:
        return None
    try:
        model = _groq_model()
        return _cached_client(
            "Groq",
            temperature,
            key,
            model,
            lambda: ChatOpenAI(
                model=model,
                api_key=key,
                base_url=GROQ_BASE_URL,
                temperature=temperature,
                # Native HTTP timeout: truly aborts hung provider calls.
                request_timeout=MODEL_TIMEOUT_SECONDS,
                max_tokens=MODEL_MAX_TOKENS,
                # Fail fast into the cascade (see _make_gemini): SDK
                # retries burn free-tier quota and delay tier fallback.
                max_retries=0,
            ),
        )
    except Exception:
        return None


def _groq_fast_model() -> str:
    """Groq Fast model ID, overridable via GROQ_FAST_MODEL env/secret."""
    try:
        override = _get_secret("GROQ_FAST_MODEL")
    except Exception:
        override = None
    if override and override.strip():
        return override.strip()
    return GROQ_FAST_MODEL


def get_tier_groq_fast_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """Groq Fast 20B: fast/simple lane, cheap-only (never final answers)."""
    key: Optional[str] = _get_secret("GROQ_API_KEY")
    if key is None:
        return None
    try:
        model = _groq_fast_model()
        return _cached_client(
            "Groq Fast",
            temperature,
            key,
            model,
            lambda: ChatOpenAI(
                model=model,
                api_key=key,
                base_url=GROQ_BASE_URL,
                temperature=temperature,
                request_timeout=MODEL_TIMEOUT_SECONDS,
                max_tokens=MODEL_MAX_TOKENS,
                max_retries=0,
            ),
        )
    except Exception:
        return None


# Cerebras helpers removed — see retired note above.
# Re-add _cerebras_model/get_tier_cerebras_llm if billing is added.


def _model_override(env_name: str, default: str) -> str:
    """Model ID override via env/secret, falling back to default."""
    try:
        override = _get_secret(env_name)
    except Exception:
        override = None
    if override and override.strip():
        return override.strip()
    return default


def _get_generic_openai_tier(
    tier: str,
    key_name: str,
    base_url: str,
    model: str,
    temperature: float,
) -> Optional[ChatOpenAI]:
    """Build a client for any OpenAI-compatible tier (shared factory).

    Missing key -> None (tier skipped; placeholder filtering lives in
    services.secrets.get_secret), cached client otherwise.
    """
    key: Optional[str] = _get_secret(key_name)
    if key is None:
        return None
    try:
        return _cached_client(
            tier,
            temperature,
            key,
            model,
            lambda: ChatOpenAI(
                model=model,
                api_key=key,
                base_url=base_url,
                temperature=temperature,
                request_timeout=MODEL_TIMEOUT_SECONDS,
                max_tokens=MODEL_MAX_TOKENS,
                # Fail fast into the cascade (see _make_gemini).
                max_retries=0,
            ),
        )
    except Exception:
        return None


def get_tier_mistral_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """Mistral tier: no-card free evaluation lane (open-weight default)."""
    return _get_generic_openai_tier(
        "Mistral",
        "MISTRAL_API_KEY",
        MISTRAL_BASE_URL,
        _model_override("MISTRAL_MODEL", MISTRAL_MODEL),
        temperature,
    )


def get_tier_cohere_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """Cohere tier: Command models via the OpenAI-compatible endpoint."""
    return _get_generic_openai_tier(
        "Cohere",
        "COHERE_API_KEY",
        COHERE_BASE_URL,
        _model_override("COHERE_MODEL", COHERE_MODEL),
        temperature,
    )


def _get_openrouter_llm(tier: str, model: str, temperature: float) -> Optional[ChatOpenAI]:
    """Build an OpenRouter client for one model (shared factory).

    Same OpenAI-compatible shape as the Groq tier; only the base URL,
    key, and model slug differ. Missing key -> None (tier skipped).
    """
    key: Optional[str] = _get_secret("OPENROUTER_API_KEY")
    if key is None:
        return None
    try:
        return _cached_client(
            tier,
            temperature,
            key,
            model,
            lambda: ChatOpenAI(
                model=model,
                api_key=key,
                base_url=OPENROUTER_BASE_URL,
                temperature=temperature,
                # Native HTTP timeout: truly aborts hung provider calls.
                request_timeout=MODEL_TIMEOUT_SECONDS,
                max_tokens=MODEL_MAX_TOKENS,
                # Fail fast into the cascade (see _make_gemini).
                max_retries=0,
            ),
        )
    except Exception:
        return None


def get_tier_openrouter_ultra_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter fallback: Nemotron 3 Ultra 550B (free tier, user pick)."""
    return _get_openrouter_llm("OpenRouter Nemotron Ultra", OPENROUTER_ULTRA_MODEL, temperature)


def get_tier_openrouter_free_router_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter Free Model Router (released Feb 2026).

    ``openrouter/free`` selects a free model at random from the live
    catalog, filtering for the request's needs (tool calling, image
    understanding, structured output).
    """
    return _get_openrouter_llm("OpenRouter Free Router", OPENROUTER_FREE_ROUTER_MODEL, temperature)


_GETTERS_BY_NAME: Dict[str, Callable[..., Optional[Any]]] = {
    "Gemini 3.8 Flash": get_tier_gemini38_llm,
    "Gemini 3.7 Flash": get_tier_gemini37_llm,
    "Gemini 3.6 Flash": get_tier2_llm,
    "Gemini 3.5 Flash": get_tier3_llm,
    "Groq": get_tier_groq_llm,
    "Groq Fast": get_tier_groq_fast_llm,
    "Cohere": get_tier_cohere_llm,
    "Mistral": get_tier_mistral_llm,
    "OpenRouter Nemotron Ultra": get_tier_openrouter_ultra_llm,
    "OpenRouter Free Router": get_tier_openrouter_free_router_llm,
}


def get_tier_llm(name: str, temperature: float = TEMPERATURE) -> Optional[Any]:
    """Fetch the cached client for a tier at a task temperature.

    Returns None for unknown tier names (e.g. test doubles) or missing
    keys. Callers needing another temperature fetch their own entry;
    cached instances are never mutated.
    """
    getter = _GETTERS_BY_NAME.get(name)
    if getter is None:
        return None
    try:
        return getter(temperature=temperature)
    except Exception:
        return None


TIER_GETTERS: list[tuple[str, Callable[[], Optional[Union[ChatOpenAI, ChatGoogleGenerativeAI]]]]] = [
    ("Gemini 3.8 Flash", get_tier_gemini38_llm),
    ("Gemini 3.7 Flash", get_tier_gemini37_llm),
    ("Gemini 3.6 Flash", get_tier2_llm),
    ("Gemini 3.5 Flash", get_tier3_llm),
    ("Groq", get_tier_groq_llm),
    ("Groq Fast", get_tier_groq_fast_llm),
    ("Cohere", get_tier_cohere_llm),
    ("OpenRouter Nemotron Ultra", get_tier_openrouter_ultra_llm),
    ("OpenRouter Free Router", get_tier_openrouter_free_router_llm),
    ("Mistral", get_tier_mistral_llm),
]


# Role-based tier tables (quota architecture): synthesis for final answers
# (quality-first, Gemini-led; Groq Fast excluded as cheap-only); cheap for
# dumb calls (classification, summaries, planning, reflection: Groq Fast
# first so Gemini quota is reserved for main answers); the full cascade
# remains the escape hatch when synthesis is down (answers then carry a
# degraded marker). Tables hold (name, getter) pairs like TIER_GETTERS.
# Gemini leads; Groq 120B is the strong fallback; Cohere -> Nemotron
# Ultra -> Free Router -> Mistral is the emergency pool. Groq's free pool
# absorbs cheap traffic; Gemini's per-model pool is spent on quality final
# answers + vision.
SMALL_FINAL_TIERS = frozenset({"Groq Fast"})  # 20B-class: never final answers
# Weak final-answer tiers: small or nondeterministic lanes that answer only
# when quality tiers are down. Runtime marks their answers degraded so the
# UI can be honest ("quality models unavailable").
WEAK_FINAL_TIERS = frozenset({
    "Groq Fast", "Mistral", "OpenRouter Free Router",
})
SYNTHESIS_TIERS: list[tuple[str, Callable[..., Optional[Any]]]] = [
    ("Gemini 3.8 Flash", get_tier_gemini38_llm),
    ("Gemini 3.7 Flash", get_tier_gemini37_llm),
    ("Gemini 3.6 Flash", get_tier2_llm),
    ("Gemini 3.5 Flash", get_tier3_llm),
    ("Groq", get_tier_groq_llm),
    ("Cohere", get_tier_cohere_llm),
    ("OpenRouter Nemotron Ultra", get_tier_openrouter_ultra_llm),
    ("OpenRouter Free Router", get_tier_openrouter_free_router_llm),
    ("Mistral", get_tier_mistral_llm),
]
CHEAP_TIERS: list[tuple[str, Callable[..., Optional[Any]]]] = [
    ("Groq Fast", get_tier_groq_fast_llm),
    ("Groq", get_tier_groq_llm),
    ("Mistral", get_tier_mistral_llm),
]

# Tiers that get the strict grounding paragraph (small or nondeterministic
# models prone to inventing citations/IDs): answer ONLY from tool results.
STRICT_GROUNDING_TIERS = frozenset({
    "Groq Fast", "Mistral", "OpenRouter Free Router",
})


TASK_TEMPERATURES: Dict[str, float] = {
    "simple": 0.5,
    "research": 0.3,
    "creative": 0.85,
    "data": 0.2,
    "code": 0.2,
    "multi_step": 0.4,
}
