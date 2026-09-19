"""Multi-tier LLM cascade: Groq -> Gemini -> OpenRouter free fallbacks.

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

load_dotenv()

GEMINI_36_MODEL: str = "gemini-3.6-flash"
GEMINI_35_MODEL: str = "gemini-3.5-flash"
# OpenCode Zen free tier retired Sep 2026 (MissingSessionID for API
# calls). 6 free lanes removed: muse-spark-1.3-contributor-free,
# nemotron-3.5-lightning-free, nemotron-3-ultra-free, big-pickle,
# mimo-v2.5-free, ling-3.0-flash-fin-free. Paid Zen models remain
# usable via https://opencode.ai/zen/v1 if billing is added.
# Groq via its OpenAI-compatible endpoint (no extra dependency needed).
# Llama models were retired from Groq in Aug 2026; gpt-oss-120b is the
# current production flagship. Override with GROQ_MODEL if needed.
GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
GROQ_MODEL: str = "openai/gpt-oss-120b"
# Cerebras retired Sep 2026: free tier now returns payment_required
# (quota/billing gate) for gpt-oss-120b — removed from cascade.
# Re-add via https://api.cerebras.ai/v1 if billing is added.
# GitHub Models via its OpenAI-compatible endpoint (same ChatOpenAI client).
# Free for every GitHub account, no card: PAT with `models:read` scope.
# Low-tier free allowance is ~150 small-model req/day at 8k in / 4k out
# tokens per request; model IDs are `provider/model` (bare names 400).
GITHUB_MODELS_BASE_URL: str = "https://models.github.ai/inference"
GITHUB_MODELS_MODEL: str = "openai/gpt-4o-mini"
# Mistral La Plateforme via its OpenAI-compatible endpoint.
# No-card free evaluation tier (rate-limited, prototyping-grade);
# open-weight default keeps the free lane usable.
MISTRAL_BASE_URL: str = "https://api.mistral.ai/v1"
MISTRAL_MODEL: str = "open-mistral-nemo"
# NVIDIA NIM via its OpenAI-compatible endpoint (same ChatOpenAI client).
# Free trial tier, no card, via an NGC API key from build.nvidia.com.
NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL: str = "meta/llama-3.1-8b-instruct"
# OpenRouter via its OpenAI-compatible endpoint (same ChatOpenAI client).
# Free models (Sept 2026; promos rotate — see
# https://openrouter.ai/models for the current free list).
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
OPENROUTER_ULTRA_MODEL: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
OPENROUTER_GEMMA_MODEL: str = "google/gemma-4-31b-it:free"
# Curated OpenRouter free models (live Sep 13 2026 via /api/v1/models;
# free = prompt+completion $0). Mirrors of OpenCode families on a
# different provider add quota diversity: when OpenCode 429s, the same
# family via OpenRouter may still answer.
OPENROUTER_NEMOTRON_SUPER_MODEL: str = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_NEMOTRON35_MODEL: str = "nvidia/nemotron-3.5-lightning:free"
OPENROUTER_GEMMA26_MODEL: str = "google/gemma-4-26b-a4b-it:free"
OPENROUTER_LING_FIN_MODEL: str = "inclusionai/ling-3.0-flash-fin:free"
# OPENROUTER_INKLING_MODEL retired Sep 2026: 403 Forbidden on free tier
# (thinkingmachines/inkling-small:free) — removed from cascade.
OPENROUTER_LAGUNA_MODEL: str = "poolside/laguna-s-2.1:free"
# OpenRouter Free Model Router (released Feb 2026): selects a free model
# at random from the live catalog, smartly filtering for features the
# request needs (tool calling, image understanding, structured output).
# It seeds quota diversity as hand-picked promos retire, so it stays a
# healthy final fallback beyond the curated list below.
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
    """
    from langchain_google_genai import ChatGoogleGenerativeAI

    base = dict(
        model=model,
        api_key=key,  # type: ignore[arg-type]
        temperature=temperature,
        request_timeout=MODEL_TIMEOUT_SECONDS,
        max_output_tokens=MODEL_MAX_TOKENS,
    )
    try:
        return ChatGoogleGenerativeAI(
            **base,  # type: ignore[arg-type]
            convert_system_message_to_human=True,  # type: ignore[call-arg]
        )
    except TypeError:
        return ChatGoogleGenerativeAI(**base)  # type: ignore[arg-type]


def get_tier2_llm(temperature: float = TEMPERATURE) -> Optional[ChatGoogleGenerativeAI]:
    """TIER 2: Gemini 3.6 Flash -- latest stable free tier (Sept 2026)."""
    key: Optional[str] = _get_secret("GEMINI_API_KEY")
    if key is None:
        return None
    try:
        return _cached_client(
            "Gemini 3.6 Flash", temperature, key, GEMINI_36_MODEL,
            lambda: _make_gemini(GEMINI_36_MODEL, key, temperature),
        )
    except Exception:
        return None


def get_tier3_llm(temperature: float = TEMPERATURE) -> Optional[ChatGoogleGenerativeAI]:
    """TIER 3: Gemini 3.5 Flash -- older fallback, still free."""
    key: Optional[str] = _get_secret("GEMINI_API_KEY")
    if key is None:
        return None
    try:
        return _cached_client(
            "Gemini 3.5 Flash", temperature, key, GEMINI_35_MODEL,
            lambda: _make_gemini(GEMINI_35_MODEL, key, temperature),
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
    """Groq tier: fast LPU inference via the OpenAI-compatible endpoint."""
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
    """Build a client for any OpenAI-compatible free tier (shared factory).

    New lanes (GitHub Models, Mistral, NVIDIA) share this shape: missing
    key -> None (tier skipped; placeholder filtering lives in
    services.secrets.get_secret), cached client otherwise. Older tiers
    keep their bespoke constructors untouched.
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
            ),
        )
    except Exception:
        return None


def get_tier_github_models_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """GitHub Models tier: free prototyping inference (PAT, models:read)."""
    return _get_generic_openai_tier(
        "GitHub Models",
        "GITHUB_MODELS_TOKEN",
        GITHUB_MODELS_BASE_URL,
        _model_override("GITHUB_MODELS_MODEL", GITHUB_MODELS_MODEL),
        temperature,
    )


def get_tier_mistral_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """Mistral tier: no-card free evaluation lane (open-weight default)."""
    return _get_generic_openai_tier(
        "Mistral",
        "MISTRAL_API_KEY",
        MISTRAL_BASE_URL,
        _model_override("MISTRAL_MODEL", MISTRAL_MODEL),
        temperature,
    )


def get_tier_nvidia_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """NVIDIA NIM tier: free-trial inference via NGC API key."""
    return _get_generic_openai_tier(
        "NVIDIA",
        "NVIDIA_API_KEY",
        NVIDIA_BASE_URL,
        _model_override("NVIDIA_MODEL", NVIDIA_MODEL),
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
            ),
        )
    except Exception:
        return None


def get_tier_openrouter_ultra_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter fallback: Nemotron 3 Ultra 550B (free tier)."""
    return _get_openrouter_llm("OpenRouter Nemotron Ultra", OPENROUTER_ULTRA_MODEL, temperature)


def get_tier_openrouter_gemma_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter fallback: Gemma 4 31B (free tier)."""
    return _get_openrouter_llm("OpenRouter Gemma", OPENROUTER_GEMMA_MODEL, temperature)


def get_tier_openrouter_nemotron_super_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter fallback: Nemotron 3 Super 120B (free tier)."""
    return _get_openrouter_llm("OpenRouter Nemotron Super", OPENROUTER_NEMOTRON_SUPER_MODEL, temperature)


def get_tier_openrouter_nemotron35_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter fallback: Nemotron 3.5 Lightning mirror (free tier)."""
    return _get_openrouter_llm("OpenRouter Nemotron 3.5", OPENROUTER_NEMOTRON35_MODEL, temperature)


def get_tier_openrouter_gemma26_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter fallback: Gemma 4 26B (free tier)."""
    return _get_openrouter_llm("OpenRouter Gemma 26B", OPENROUTER_GEMMA26_MODEL, temperature)


def get_tier_openrouter_ling_fin_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter fallback: Ling 3.0 Flash Fin mirror (free tier)."""
    return _get_openrouter_llm("OpenRouter Ling Fin", OPENROUTER_LING_FIN_MODEL, temperature)


def get_tier_openrouter_laguna_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter fallback: Laguna code model (free tier)."""
    return _get_openrouter_llm("OpenRouter Laguna", OPENROUTER_LAGUNA_MODEL, temperature)


def get_tier_openrouter_free_router_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """OpenRouter Free Model Router (released Feb 2026).

    ``openrouter/free`` selects a free model at random from the live
    catalog, filtering for the request's needs (tool calling, image
    understanding, structured output). Survives promo rotation of the
    hand-picked model list below.
    """
    return _get_openrouter_llm("OpenRouter Free Router", OPENROUTER_FREE_ROUTER_MODEL, temperature)


_GETTERS_BY_NAME: Dict[str, Callable[..., Optional[Any]]] = {
    "Groq": get_tier_groq_llm,
    "Gemini 3.6 Flash": get_tier2_llm,
    "Gemini 3.5 Flash": get_tier3_llm,
    "GitHub Models": get_tier_github_models_llm,
    "Mistral": get_tier_mistral_llm,
    "NVIDIA": get_tier_nvidia_llm,
    "OpenRouter Nemotron Ultra": get_tier_openrouter_ultra_llm,
    "OpenRouter Gemma": get_tier_openrouter_gemma_llm,
    "OpenRouter Nemotron Super": get_tier_openrouter_nemotron_super_llm,
    "OpenRouter Nemotron 3.5": get_tier_openrouter_nemotron35_llm,
    "OpenRouter Gemma 26B": get_tier_openrouter_gemma26_llm,
    "OpenRouter Ling Fin": get_tier_openrouter_ling_fin_llm,
    "OpenRouter Laguna": get_tier_openrouter_laguna_llm,
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
    ("Groq", get_tier_groq_llm),
    ("Gemini 3.6 Flash", get_tier2_llm),
    ("Gemini 3.5 Flash", get_tier3_llm),
    ("GitHub Models", get_tier_github_models_llm),
    ("NVIDIA", get_tier_nvidia_llm),
    ("OpenRouter Nemotron Ultra", get_tier_openrouter_ultra_llm),
    ("OpenRouter Gemma", get_tier_openrouter_gemma_llm),
    ("OpenRouter Nemotron Super", get_tier_openrouter_nemotron_super_llm),
    ("OpenRouter Nemotron 3.5", get_tier_openrouter_nemotron35_llm),
    ("OpenRouter Gemma 26B", get_tier_openrouter_gemma26_llm),
    ("OpenRouter Ling Fin", get_tier_openrouter_ling_fin_llm),
    ("OpenRouter Laguna", get_tier_openrouter_laguna_llm),
    ("OpenRouter Free Router", get_tier_openrouter_free_router_llm),
    ("Mistral", get_tier_mistral_llm),
]


# Role-based tier tables (quota architecture): synthesis for final answers
# (quality-first, Gemini-led, no 8B-class tiers); cheap for dumb calls
# (classification, summaries, planning, reflection); the full cascade
# remains the escape hatch when synthesis is down (answers then carry a
# degraded marker). Tables hold (name, getter) pairs like TIER_GETTERS.
SMALL_FINAL_TIERS = frozenset({"NVIDIA"})  # 8B-class: never final answers
# Weak final-answer tiers: small or nondeterministic lanes that answer only
# when quality tiers are down. Runtime marks their answers degraded so the
# UI can be honest ("quality models unavailable"). Shape of SYNTHESIS_TIERS
# is unchanged (see test_role_tables_shape); order stays quality-first with
# these lanes last.
WEAK_FINAL_TIERS = frozenset({
    "Mistral", "OpenRouter Gemma 26B", "OpenRouter Ling Fin",
    "OpenRouter Laguna", "OpenRouter Free Router",
})
SYNTHESIS_TIERS: list[tuple[str, Callable[..., Optional[Any]]]] = [
    ("Gemini 3.6 Flash", get_tier2_llm),
    ("Gemini 3.5 Flash", get_tier3_llm),
    ("Groq", get_tier_groq_llm),
    ("GitHub Models", get_tier_github_models_llm),
    ("OpenRouter Nemotron Ultra", get_tier_openrouter_ultra_llm),
    ("OpenRouter Nemotron Super", get_tier_openrouter_nemotron_super_llm),
    ("OpenRouter Gemma", get_tier_openrouter_gemma_llm),
    ("OpenRouter Nemotron 3.5", get_tier_openrouter_nemotron35_llm),
    ("OpenRouter Gemma 26B", get_tier_openrouter_gemma26_llm),
    ("OpenRouter Ling Fin", get_tier_openrouter_ling_fin_llm),
    ("OpenRouter Laguna", get_tier_openrouter_laguna_llm),
    ("OpenRouter Free Router", get_tier_openrouter_free_router_llm),
    ("Mistral", get_tier_mistral_llm),
]
CHEAP_TIERS: list[tuple[str, Callable[..., Optional[Any]]]] = [
    ("Groq", get_tier_groq_llm),
    ("GitHub Models", get_tier_github_models_llm),
    ("NVIDIA", get_tier_nvidia_llm),
    ("Mistral", get_tier_mistral_llm),
]

# Tiers that get the strict grounding paragraph (small or nondeterministic
# models prone to inventing citations/IDs): answer ONLY from tool results.
STRICT_GROUNDING_TIERS = frozenset({
    "NVIDIA", "Mistral", "OpenRouter Gemma 26B", "OpenRouter Free Router",
})


TASK_TEMPERATURES: Dict[str, float] = {
    "simple": 0.5,
    "research": 0.3,
    "creative": 0.85,
    "data": 0.2,
    "code": 0.2,
    "multi_step": 0.4,
}
