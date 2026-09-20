"""Request routing: deterministic rules first, LLM classifier on ambiguity.

Routing only selects temperature/planning policy — tool choice always
stays with the model, so a wrong route degrades gracefully instead of
breaking tool use.
"""

import logging
import re
import threading
from typing import Dict, Optional, Sequence

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import HumanMessage

from agent.budget import RequestBudget
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.prompts import _as_text
from services.normalize import normalize_text as _normalize_text

logger = logging.getLogger(__name__)

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|yo|good\s?(morning|afternoon|evening|night)"
    r"|thanks|thank you|bye|ok|okay|sure|yes|no)\b[?!.]*$",
    re.IGNORECASE,
)
_UPLOAD_ID_RE = re.compile(r"[0-9a-f]{16}")


# --- classifier-fallthrough telemetry (Milestone 1a) ---
# In-memory counters of rule_route inputs that match nothing, keyed by a
# scrubbed normalization (lowercase, digits→<n>, tokens containing @
# dropped, punctuation stripped, 80 chars). Raw user text never reaches
# persistent logs; read the counters via get_fallthrough_stats() (the ops
# endpoint will expose them). Bounded LRU (200 keys) + 1h TTL; never raises.
_FALLTHROUGH_MAX_KEYS: int = 200
_FALLTHROUGH_TTL: float = 3600.0
_fallthrough_lock = threading.Lock()
_fallthrough_total: int = 0
_fallthrough_counts: Dict[str, int] = {}
_fallthrough_when: Dict[str, float] = {}


def _scrub_fallthrough(text: str) -> str:
    """Normalize an input for pattern mining without keeping PII."""
    try:
        parts: list = []
        for tok in str(text or "").lower().split():
            if "@" in tok:
                continue
            tok = re.sub(r"\d+", "<n>", tok)
            tok = re.sub(r"[^\w<>\-]", "", tok).strip()
            if tok:
                parts.append(tok)
        return " ".join(parts)[:80]
    except Exception:
        return ""


def _record_routed() -> None:
    """Count one deterministically routed input. Never raises."""
    global _fallthrough_total
    try:
        with _fallthrough_lock:
            _fallthrough_total += 1
    except Exception:
        logger.debug("routed counter failed", exc_info=True)


def _record_fallthrough(text: str) -> None:
    """Count one unmatched input (and one total call). Never raises."""
    global _fallthrough_total
    try:
        import time as _time

        now = _time.time()
        with _fallthrough_lock:
            _fallthrough_total += 1
            # Opportunistic TTL sweep.
            if len(_fallthrough_when) > _FALLTHROUGH_MAX_KEYS * 2:
                for k, ts in list(_fallthrough_when.items()):
                    if now - ts > _FALLTHROUGH_TTL:
                        _fallthrough_when.pop(k, None)
                        _fallthrough_counts.pop(k, None)
            key = _scrub_fallthrough(text)
            if not key:
                return
            if key not in _fallthrough_counts and len(_fallthrough_counts) >= _FALLTHROUGH_MAX_KEYS:
                # Evict oldest.
                try:
                    oldest = min(_fallthrough_when, key=lambda k: _fallthrough_when.get(k, now))
                    _fallthrough_when.pop(oldest, None)
                    _fallthrough_counts.pop(oldest, None)
                except ValueError:
                    return
            _fallthrough_counts[key] = _fallthrough_counts.get(key, 0) + 1
            _fallthrough_when[key] = now
    except Exception:
        logger.debug("fallthrough counter failed", exc_info=True)


def get_fallthrough_stats(limit: int = 50) -> Dict[str, object]:
    """Return {total, fallthrough, top: [(pattern, count)]} (copy, never raises)."""
    try:
        with _fallthrough_lock:
            items = sorted(_fallthrough_counts.items(),
                           key=lambda kv: kv[1], reverse=True)
            return {"total": _fallthrough_total,
                    "fallthrough": sum(_fallthrough_counts.values()),
                    "top": [(k, v) for k, v in items[:max(1, limit)]]}
    except Exception:
        return {"total": 0, "fallthrough": 0, "top": []}


def _reset_fallthrough_stats() -> None:
    """Clear counters (tests/ops only)."""
    global _fallthrough_total
    try:
        with _fallthrough_lock:
            _fallthrough_total = 0
            _fallthrough_counts.clear()
            _fallthrough_when.clear()
    except Exception:
        logger.debug("fallthrough reset failed", exc_info=True)


def _match_keyword(text: str, word: str) -> bool:
    """Match one keyword against already-lowercased text.

    Plain words match whole words only ("read" must not match
    "already", "plot" must not match "exploit"); a trailing "*"
    marks a stem ("summar*" matches summarize/summary); entries
    starting with a non-letter (".pdf") or multi-word phrases match
    literally with boundary guards. Single words len>=4 also get a
    typo-tolerant fallback (same first letter, len diff<=2, ratio>=80)
    so "craete" still hits "create" even when normalization misses.
    """
    w = word.strip().lower()
    if not w:
        return False
    if w.endswith("*") and len(w) > 1:
        return re.search(r"\b" + re.escape(w[:-1]) + r"\w*", text) is not None
    if w[0].isalnum():
        if re.search(r"\b" + re.escape(w) + r"\b", text) is not None:
            return True
        # Fuzzy fallback: single words only, len>=4, never for short
        # tokens ("do"/"to" must never match "doc").
        try:
            if " " in w or len(w) < 4:
                return False
            try:
                from services.normalize import _ratio as _fuzz_ratio
            except Exception:
                import difflib as _difflib

                def _fuzz_ratio(a: str, b: str) -> float:
                    try:
                        return float(_difflib.SequenceMatcher(None, a, b).ratio() * 100.0)
                    except Exception:
                        return 0.0

            for tok in re.findall(r"[a-z0-9]+", text):
                if len(tok) < 4 or tok == w:
                    continue
                if abs(len(tok) - len(w)) > 2:
                    continue
                if tok[0] != w[0]:
                    continue
                try:
                    if _fuzz_ratio(tok, w) >= 80.0:
                        return True
                except Exception:
                    logger.debug("router fuzzy match failed", exc_info=True)
                    continue
        except Exception:
            logger.debug("router keyword match failed", exc_info=True)
        return False
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
    raw = user_input.lower().strip()
    if not raw:
        _record_routed()
        return "simple"
    if _GREETING_RE.match(raw) and len(raw) <= 40:
        _record_routed()
        return "simple"
    # Normalize once: typo-correct + canonicalize creation verbs
    # ("turn/convrt" -> "create") so downstream lists stay small.
    try:
        text = _normalize_text(user_input)
    except Exception:
        text = raw
    hits = set()
    if _signals(text, ["pdf", ".pdf", "read", "summar*", "document", "docx", ".docx", "doc", ".doc", "odt", ".odt", "rtf", ".rtf", "txt", ".txt", "md", ".md", "markdown", "pptx", ".pptx", "ppt", ".ppt", "odp", ".odp", "html", ".html", ".htm", "xml", ".xml", "zip", ".zip", "archive", "webpage", "web page", "text file", "what is it", "what does", "teach*", "learn*", "exam", "exams", "recall", "lecture*", "tutor*", "practic*", "quiz*"]):
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
         "update the",
         # Creation verbs (normalized: turn/convert/make/generate/build -> create).
         "create", "generate", "build", "produce", "prepare",
         "turn into", "convert into", "make a", "create a", "build a"],
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
        _record_routed()
        return next(iter(hits))
    if len(hits) > 1:
        _record_routed()
        return "multi_step"
    _record_fallthrough(user_input)
    return None


def rule_route_conf(user_input: str) -> tuple:
    """Deterministic route plus confidence (never raises).

    Returns (task_type_or_None, confidence 0-1). Single-bucket exact
    hits score 0.9, multi-bucket 0.7, typo-corrected-only hits 0.6,
    fallthrough 0.0. Callers use <0.6 to ask "Did you mean...?"
    instead of silently defaulting to simple.
    NOTE: calls rule_route (which records stats) once — no extra counting here.
    """
    try:
        task = rule_route(user_input)
    except Exception:
        return (None, 0.0)
    if task is None:
        return (None, 0.0)
    if task == "multi_step":
        return (task, 0.7)
    try:
        from services.normalize import get_display_corrections as _corr

        if _corr(user_input):
            return (task, 0.6)
    except Exception:
        logger.debug("route confidence corrections failed", exc_info=True)
    return (task, 0.9)


def get_route_corrections(user_input: str) -> list:
    """[(orig, fixed)] probable-typo corrections for UX notes (never raises).

    Display-filtered: routing-internal rewrites (verb canonicalization),
    capitalized proper nouns, and affix/stemming maps are never shown.
    """
    try:
        from services.normalize import get_display_corrections as _corr

        pairs = _corr(user_input)
        return [(str(o), str(n)) for o, n in (pairs or [])]
    except Exception:
        return []


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
    # Fail open to multi_step (keeps tools) rather than simple (disables them).
    return category if category in valid else "multi_step"


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
        # Deny-safe: classifier failure must never take down the turn.
        return ("none", 0.0)
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
