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


def _match_keyword(text: str, word: str) -> bool:
    """Match one keyword against already-lowercased text.

    Plain words match whole words only ("read" must not match
    "already", "plot" must not match "exploit"); a trailing "*"
    marks a stem ("summar*" matches summarize/summary); entries
    starting with a non-letter (".pdf") or multi-word phrases match
    literally with boundary guards.
    """
    w = word.strip().lower()
    if not w:
        return False
    if w.endswith("*") and len(w) > 1:
        return re.search(r"\b" + re.escape(w[:-1]) + r"\w*", text) is not None
    if w[0].isalnum():
        return re.search(r"\b" + re.escape(w) + r"\b", text) is not None
    return w in text


def _signals(text: str, words: Sequence[str]) -> bool:
    """True when any keyword matches the text (see _match_keyword)."""
    return any(_match_keyword(text, w) for w in words)


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
    if _UPLOAD_ID_RE.search(text) or _signals(text, ["pdf", ".pdf", "read", "summar*", "document", "docx", ".docx", "doc", ".doc", "odt", ".odt", "rtf", ".rtf", "txt", ".txt", "md", ".md", "markdown", "pptx", ".pptx", "ppt", ".ppt", "odp", ".odp", "html", ".html", ".htm", "xml", ".xml", "zip", ".zip", "archive", "webpage", "web page", "text file", "what is it", "what does", "teach*", "learn*", "exam", "exams", "recall", "lecture*", "tutor*"]):
        hits.add("research")
    if _signals(text, ["csv", ".csv", "tsv", ".tsv", "xlsx", ".xlsx", "xls", ".xls", "ods", ".ods", "json", ".json", "analyz*", "spreadsheet", "dataset", "chart", "plot", "data table"]):
        hits.add("data")
    if _signals(
        text,
        [".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", "python", "javascript",
         "typescript", "java ", "golang", "rust ", "code", "coding", "script", "program",
         "function", "debug", "traceback", "stack trace", "exception", "compile",
         "run the code", "execute", "pytest", "npm", "node", "pip install", "fix the bug",
         "refactor", "unit test"],
    ):
        hits.add("data")
    if _signals(
        text,
        ["presentation", "slides", "pptx", "powerpoint", "essay", "report",
         "resume", "write", "draft", "compose", "letter", "docx", "word document",
         ".pdf", "pdf file", "as pdf", "to pdf", "into pdf", "export",
         ".md", "markdown file", "revise", "revis*", "edit the",
         "update the"],
    ):
        hits.add("creative")
    if _signals(
        text,
        ["latest", "recent", "current", "today", "news", "search", "look up", "find out"],
    ):
        hits.add("research")
    if _signals(
        text,
        ["logic", "premise*", "conclusion", "valid*", "truth table", "syllogism",
         "entail*", "proposition*", "modus", "affirming", "check_logic", "tautology",
         "contradiction", "satisfiab*"],
    ):
        hits.add("data")
    # Entertainment factual: song/movie/people questions need web verification
    # (free-tier memory hallucinates credits) — but the verb decides:
    # write/compose/make a song is creative, who-sang/lyrics-of is research.
    # ponytail: keyword list covers the misfire class from the tere-liye
    # screenshot; extend only when a new factual class hallucinates.
    if _signals(text, ["who sang", "who wrote", "lyrics of", "lyric of",
                       "song from", "songs from", "movie of", "film of",
                       "cast of", "singer of", "music by", "sung by",
                       "released", "starring", "starred", "directed by"]):
        hits.add("research")
    elif _signals(text, ["song", "songs", "singer", "lyrics", "lyric",
                         "movie", "film", "actor", "actress", "album",
                         "cast", "soundtrack"]) and not _signals(
            text, ["write", "compose", "draft", "create", "make me", "generate"]):
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
    tier_name: Optional[str] = None,
) -> str:
    """Classify a request: simple, research, creative, data, or multi_step."""
    prompt = (
        "Classify this request into exactly one category:\n"
        "- simple: Direct question, no tools needed\n"
        "- research: Needs web search, document reading, or entertainment facts (songs/movies/people credits)\n"
        "- creative: Needs file generation (presentation, essay)\n"
        "- data: Needs CSV/data analysis OR coding (write/run/debug code) OR logic check (validity/truth table)\n"
        "- multi_step: Combines multiple tools\n\n"
        f"Request: {user_input}\nCategory:"
    )
    response = agent._invoke_bounded(llm_instance, [HumanMessage(content=prompt)], budget=budget, tier_name=tier_name)
    category = _as_text(response.content).strip().lower()
    valid = ["simple", "research", "creative", "data", "multi_step"]
    return category if category in valid else "simple"


_ATTACHMENT_INTENTS = ("vision", "document", "presentation", "web", "none")


def classify_attachment_need(
    user_input: str,
    available_kinds: Sequence[str],
    llm_instance: BaseLanguageModel,
    budget: Optional[RequestBudget] = None,
) -> tuple:
    """Auxiliary attachment intent: which historical resource (if any) applies.

    Returns (intent, confidence) where intent is one of
    vision|document|presentation|web|none. Small structured prompt so the
    chatflow gate only pays for it on ambiguous pronouns. Never raises:
    parse failures yield ("none", 0.0) so callers deny safely.
    """
    kinds = ", ".join(str(k) for k in (available_kinds or []) if k) or "none"
    prompt = (
        "Decide which prior attachment the current request refers to.\n"
        f"Available kinds: {kinds}.\n"
        "Reply exactly two lines:\n"
        "intent: <vision|document|presentation|web|none>\n"
        "confidence: <0-1>\n"
        "- vision: refers to a prior image/photo/screenshot\n"
        "- document: refers to a prior PDF/document/CSV\n"
        "- presentation: refers to a prior PPT/PPTX/slides\n"
        "- web: new search/music/code question, no prior file needed\n"
        "- none: no prior file needed\n\n"
        f"Request: {user_input}\n"
    )
    try:
        response = agent._invoke_bounded(llm_instance, [HumanMessage(content=prompt)], budget=budget)
        text = _as_text(response.content).strip().lower()
    except Exception:
        raise
    intent = "none"
    conf = 0.0
    try:
        m_intent = re.search(r"intent\s*:\s*(vision|document|presentation|web|none)", text)
        if m_intent:
            intent = m_intent.group(1)
        m_conf = re.search(r"confidence\s*:\s*(0(?:\.\d+)?|1(?:\.0+)?)", text)
        if m_conf:
            conf = max(0.0, min(1.0, float(m_conf.group(1))))
        if intent not in _ATTACHMENT_INTENTS:
            return ("none", 0.0)
        return (intent, conf)
    except Exception:
        return ("none", 0.0)
