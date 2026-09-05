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
    get_tier1_llm,
    get_tier1b_llm,
    get_tier2_llm,
    get_tier3_llm,
)

TIER_AGENT_GETTERS: List[
    Tuple[str, Callable[[], Optional[Union[ChatOpenAI, ChatGoogleGenerativeAI]]]]
] = [
    ("Muse Spark 1.3", get_tier1_llm),  # type: ignore[arg-type]
    ("Nemotron 3.5", get_tier1b_llm),  # type: ignore[arg-type]
    ("Gemini 3.6 Flash", get_tier2_llm),  # type: ignore[arg-type]
    ("Gemini 3.5 Flash", get_tier3_llm),  # type: ignore[arg-type]
]
