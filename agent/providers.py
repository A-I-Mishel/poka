"""Provider tier table: cascade order and construction entry points.

Boundary: config.py constructs provider clients (model, temperature,
native timeouts); this table only fixes cascade ORDER and hands the
cascade callables. Selection, cooldown, and fallback live in
agent.cascade; invocation in agent.executor; error translation in
agent.cascade.classify_provider_error.
"""

from typing import Callable, List, Optional, Tuple, Union

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from config import (
    get_tier2_llm,
    get_tier3_llm,
    get_tier_cerebras_llm,
    get_tier_github_models_llm,
    get_tier_groq_llm,
    get_tier_mistral_llm,
    get_tier_nvidia_llm,
    get_tier_openrouter_free_router_llm,
    get_tier_openrouter_gemma26_llm,
    get_tier_openrouter_gemma_llm,
    get_tier_openrouter_laguna_llm,
    get_tier_openrouter_ling_fin_llm,
    get_tier_openrouter_nemotron35_llm,
    get_tier_openrouter_nemotron_super_llm,
    get_tier_openrouter_ultra_llm,
)

TIER_AGENT_GETTERS: List[
    Tuple[str, Callable[[], Optional[Union[ChatOpenAI, ChatGoogleGenerativeAI]]]]
] = [
    ("Groq", get_tier_groq_llm),  # type: ignore[arg-type]
    ("Cerebras", get_tier_cerebras_llm),  # type: ignore[arg-type]
    ("Gemini 3.6 Flash", get_tier2_llm),  # type: ignore[arg-type]
    ("Gemini 3.5 Flash", get_tier3_llm),  # type: ignore[arg-type]
    ("GitHub Models", get_tier_github_models_llm),  # type: ignore[arg-type]
    ("Mistral", get_tier_mistral_llm),  # type: ignore[arg-type]
    ("NVIDIA", get_tier_nvidia_llm),  # type: ignore[arg-type]
    ("OpenRouter Nemotron Ultra", get_tier_openrouter_ultra_llm),  # type: ignore[arg-type]
    ("OpenRouter Gemma", get_tier_openrouter_gemma_llm),  # type: ignore[arg-type]
    ("OpenRouter Nemotron Super", get_tier_openrouter_nemotron_super_llm),  # type: ignore[arg-type]
    ("OpenRouter Nemotron 3.5", get_tier_openrouter_nemotron35_llm),  # type: ignore[arg-type]
    ("OpenRouter Gemma 26B", get_tier_openrouter_gemma26_llm),  # type: ignore[arg-type]
    ("OpenRouter Ling Fin", get_tier_openrouter_ling_fin_llm),  # type: ignore[arg-type]
    ("OpenRouter Laguna", get_tier_openrouter_laguna_llm),  # type: ignore[arg-type]
    ("OpenRouter Free Router", get_tier_openrouter_free_router_llm),  # type: ignore[arg-type]
]
