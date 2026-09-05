"""Multi-tier LLM cascade: Muse Spark 1.3 -> Nemotron 3.5 (OpenCode free) -> Gemini 3.6 -> Gemini 3.5."""

import hashlib
import secrets
import threading
from typing import Any, Callable, Dict, Optional, Tuple, Union
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from services.limits import MODEL_TIMEOUT_SECONDS
from services.secrets import get_secret

load_dotenv()

MUSE_MODEL: str = "muse-spark-1.3-contributor-free"
FREE_MODEL: str = "nemotron-3.5-lightning-free"
GEMINI_36_MODEL: str = "gemini-3.6-flash"
GEMINI_35_MODEL: str = "gemini-3.5-flash"
OPENCODE_BASE_URL: str = "https://opencode.ai/zen/v1"
TEMPERATURE: float = 0.7

# Client cache: clients hold only model config + credentials (no user
# data, prompts, or memories), so sharing them process-wide is safe and
# avoids paying construction (~60ms OpenAI, ~700ms Gemini) on every tier
# use. Keyed by (tier, temperature); the active key is re-checked on
# every lookup so rotation takes effect promptly. Only a hash of the key
# is retained for that comparison, never the key itself beyond what the
# client object requires. Bounded keyspace (4 tiers x task temperatures)
# plus a hard cap; instances are never mutated after caching (callers
# needing another temperature fetch their own entry via get_tier_llm).
_CLIENT_CACHE: Dict[Tuple[str, float], Tuple[str, Any]] = {}
_CLIENT_CACHE_LOCK = threading.Lock()
_MAX_CACHED_CLIENTS: int = 32


def _key_fingerprint(key: str) -> str:
    """Non-reversible identity for cache rotation checks (never logged)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _cached_client(tier: str, temperature: float, key: str, make: Callable[[], Any]) -> Any:
    """Return the cached client for (tier, temperature, key), building once."""
    cache_key = (tier, float(temperature))
    fingerprint = _key_fingerprint(key)
    with _CLIENT_CACHE_LOCK:
        hit = _CLIENT_CACHE.get(cache_key)
        if hit is not None and secrets.compare_digest(hit[0], fingerprint):
            return hit[1]
    client = make()
    with _CLIENT_CACHE_LOCK:
        if len(_CLIENT_CACHE) >= _MAX_CACHED_CLIENTS:
            _CLIENT_CACHE.clear()
        _CLIENT_CACHE[cache_key] = (fingerprint, client)
    return client


def _get_secret(name: str) -> Optional[str]:
    """Read a secret from Streamlit Cloud secrets first, then env/.env.

    Thin wrapper over the central services.secrets seam (kept for
    backward compatibility).

    Args:
        name: Secret name, e.g. "GEMINI_API_KEY".

    Returns:
        The secret value, or None if not set anywhere.
    """
    return get_secret(name)


def _is_placeholder(value: Optional[str], placeholder: str) -> bool:
    """Check for missing or unreplaced placeholder secrets."""
    return not value or value.strip() in ("", placeholder)


def get_tier1_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """TIER 1: Muse Spark 1.3 via OpenCode -- limited-time free tier."""
    key: Optional[str] = _get_secret("OPENCODE_API_KEY")
    if _is_placeholder(key, "your_opencode_key_here"):
        return None
    assert key is not None
    try:
        return _cached_client(
            "Muse Spark 1.3",
            temperature,
            key,
            lambda: ChatOpenAI(
                model=MUSE_MODEL,
                api_key=key,
                base_url=OPENCODE_BASE_URL,
                temperature=temperature,
                # Native HTTP timeout: truly aborts hung provider calls.
                request_timeout=MODEL_TIMEOUT_SECONDS,
            ),
        )
    except Exception:
        return None


def get_tier1b_llm(temperature: float = TEMPERATURE) -> Optional[ChatOpenAI]:
    """TIER 1B: Nemotron 3.5 Lightning via OpenCode -- free tier, separate quota."""
    key: Optional[str] = _get_secret("OPENCODE_API_KEY")
    if _is_placeholder(key, "your_opencode_key_here"):
        return None
    assert key is not None
    try:
        return _cached_client(
            "Nemotron 3.5",
            temperature,
            key,
            lambda: ChatOpenAI(
                model=FREE_MODEL,
                api_key=key,
                base_url=OPENCODE_BASE_URL,
                temperature=temperature,
                # Native HTTP timeout: truly aborts hung provider calls.
                request_timeout=MODEL_TIMEOUT_SECONDS,
            ),
        )
    except Exception:
        return None


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
    if _is_placeholder(key, "your_gemini_key_here"):
        return None
    assert key is not None
    try:
        return _cached_client(
            "Gemini 3.6 Flash", temperature, key,
            lambda: _make_gemini(GEMINI_36_MODEL, key, temperature),
        )
    except Exception:
        return None


def get_tier3_llm(temperature: float = TEMPERATURE) -> Optional[ChatGoogleGenerativeAI]:
    """TIER 3: Gemini 3.5 Flash -- older fallback, still free."""
    key: Optional[str] = _get_secret("GEMINI_API_KEY")
    if _is_placeholder(key, "your_gemini_key_here"):
        return None
    assert key is not None
    try:
        return _cached_client(
            "Gemini 3.5 Flash", temperature, key,
            lambda: _make_gemini(GEMINI_35_MODEL, key, temperature),
        )
    except Exception:
        return None


_GETTERS_BY_NAME: Dict[str, Callable[..., Optional[Any]]] = {
    "Muse Spark 1.3": get_tier1_llm,
    "Nemotron 3.5": get_tier1b_llm,
    "Gemini 3.6 Flash": get_tier2_llm,
    "Gemini 3.5 Flash": get_tier3_llm,
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
    ("Muse Spark 1.3", get_tier1_llm),
    ("Nemotron 3.5", get_tier1b_llm),
    ("Gemini 3.6 Flash", get_tier2_llm),
    ("Gemini 3.5 Flash", get_tier3_llm),
]


TASK_TEMPERATURES: Dict[str, float] = {
    "simple": 0.5,
    "research": 0.3,
    "creative": 0.85,
    "data": 0.2,
    "multi_step": 0.4,
}
