"""Multi-tier LLM cascade: Muse Spark 1.3 -> Nemotron 3.5 (OpenCode free) -> Gemini 3.6 -> Gemini 3.5."""

import os
from typing import Callable, Dict, Optional, Union
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

MUSE_MODEL: str = "muse-spark-1.3-contributor-free"
FREE_MODEL: str = "nemotron-3.5-lightning-free"
GEMINI_36_MODEL: str = "gemini-3.6-flash"
GEMINI_35_MODEL: str = "gemini-3.5-flash"
OPENCODE_BASE_URL: str = "https://opencode.ai/zen/v1"
TEMPERATURE: float = 0.7


def _get_secret(name: str) -> Optional[str]:
    """Read a secret from Streamlit Cloud secrets first, then env/.env.

    Args:
        name: Secret name, e.g. "GEMINI_API_KEY".

    Returns:
        The secret value, or None if not set anywhere.
    """
    try:
        import streamlit as st

        # load_if_toml_exists() never raises or prints when no file exists
        # (plain st.secrets access would st.error + break set_page_config order).
        if st.secrets.load_if_toml_exists():
            val = st.secrets.get(name)
            if val:
                return str(val)
    except Exception:
        pass
    return os.getenv(name)


def _is_placeholder(value: Optional[str], placeholder: str) -> bool:
    """Check for missing or unreplaced placeholder secrets."""
    return not value or value.strip() in ("", placeholder)


def get_tier1_llm() -> Optional[ChatOpenAI]:
    """TIER 1: Muse Spark 1.3 via OpenCode -- limited-time free tier."""
    key: Optional[str] = _get_secret("OPENCODE_API_KEY")
    if _is_placeholder(key, "your_opencode_key_here"):
        return None
    try:
        return ChatOpenAI(
            model=MUSE_MODEL,
            api_key=key,
            base_url=OPENCODE_BASE_URL,
            temperature=TEMPERATURE,
        )
    except Exception:
        return None


def get_tier1b_llm() -> Optional[ChatOpenAI]:
    """TIER 1B: Nemotron 3.5 Lightning via OpenCode -- free tier, separate quota."""
    key: Optional[str] = _get_secret("OPENCODE_API_KEY")
    if _is_placeholder(key, "your_opencode_key_here"):
        return None
    try:
        return ChatOpenAI(
            model=FREE_MODEL,
            api_key=key,
            base_url=OPENCODE_BASE_URL,
            temperature=TEMPERATURE,
        )
    except Exception:
        return None


def _make_gemini(model: str, key: str, temperature: float):
    """Build ChatGoogleGenerativeAI across langchain-google-genai versions.

    Older releases accept convert_system_message_to_human; newer ones
    (4.x, consolidated google-genai SDK) deprecated/removed it.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI

    try:
        return ChatGoogleGenerativeAI(
            model=model,
            api_key=key,  # type: ignore[arg-type]
            temperature=temperature,
            convert_system_message_to_human=True,  # type: ignore[call-arg]
        )
    except TypeError:
        return ChatGoogleGenerativeAI(
            model=model,
            api_key=key,  # type: ignore[arg-type]
            temperature=temperature,
        )


def get_tier2_llm() -> Optional[ChatGoogleGenerativeAI]:
    """TIER 2: Gemini 3.6 Flash -- latest stable free tier (Sept 2026)."""
    key: Optional[str] = _get_secret("GEMINI_API_KEY")
    if _is_placeholder(key, "your_gemini_key_here"):
        return None
    try:
        assert key is not None
        return _make_gemini(GEMINI_36_MODEL, key, TEMPERATURE)
    except Exception:
        return None


def get_tier3_llm() -> Optional[ChatGoogleGenerativeAI]:
    """TIER 3: Gemini 3.5 Flash -- older fallback, still free."""
    key: Optional[str] = _get_secret("GEMINI_API_KEY")
    if _is_placeholder(key, "your_gemini_key_here"):
        return None
    try:
        assert key is not None
        return _make_gemini(GEMINI_35_MODEL, key, TEMPERATURE)
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
