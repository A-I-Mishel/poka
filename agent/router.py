"""Request routing: deterministic rules first, LLM classifier on ambiguity.

Routing only selects temperature/planning policy — tool choice always
stays with the model, so a wrong route degrades gracefully instead of
breaking tool use.
"""

import re
from typing import Optional, Sequence

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import HumanMessage

from agent.budget import RequestBudget
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.prompts import _as_text

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|yo|good\s?(morning|afternoon|evening|night)"
    r"|thanks|thank you|bye|ok|okay|sure|yes|no)\b[?!.]*$",
    re.IGNORECASE,
)
_UPLOAD_ID_RE = re.compile(r"[0-9a-f]{16}")


def _signals(text: str, words: Sequence[str]) -> bool:
    """True when any keyword appears in the text."""
    return any(w in text for w in words)


def rule_route(user_input: str) -> Optional[str]:
    """Deterministically classify obvious requests without a model call.

    Returns a task type, or None when ambiguous (caller falls back to the
    LLM classifier). Routing only selects temperature/planning policy —
    tool choice always stays with the model, so a wrong route degrades
    gracefully instead of breaking tool use.
    """
    text = user_input.lower().strip()
    if not text:
        return "simple"
    if _GREETING_RE.match(text) and len(text) <= 40:
        return "simple"
    hits = set()
    if _UPLOAD_ID_RE.search(text) or _signals(text, ["pdf", ".pdf", "read", "summar", "document"]):
        hits.add("research")
    if _signals(text, ["csv", "analyz", "spreadsheet", "dataset", "chart", "plot", "data table"]):
        hits.add("data")
    if _signals(
        text,
        ["presentation", "slides", "pptx", "powerpoint", "essay", "report",
         "resume", "write", "draft", "letter", "docx", "word document"],
    ):
        hits.add("creative")
    if _signals(
        text,
        ["latest", "recent", "current", "today", "news", "search", "look up", "find out"],
    ):
        hits.add("research")
    if len(hits) == 1:
        return next(iter(hits))
    if len(hits) > 1:
        return "multi_step"
    return None


def classify_task(
    user_input: str,
    llm_instance: BaseLanguageModel,
    budget: Optional[RequestBudget] = None,
) -> str:
    """Classify a request: simple, research, creative, data, or multi_step."""
    prompt = (
        "Classify this request into exactly one category:\n"
        "- simple: Direct question, no tools needed\n"
        "- research: Needs web search or document reading\n"
        "- creative: Needs file generation (presentation, essay)\n"
        "- data: Needs CSV/data analysis\n"
        "- multi_step: Combines multiple tools\n\n"
        f"Request: {user_input}\nCategory:"
    )
    response = agent._invoke_bounded(llm_instance, [HumanMessage(content=prompt)], budget=budget)
    category = _as_text(response.content).strip().lower()
    valid = ["simple", "research", "creative", "data", "multi_step"]
    return category if category in valid else "simple"
