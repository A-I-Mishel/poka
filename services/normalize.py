"""Input normalization: typo correction + verb canonicalization (single source).

Replaces scattered hard-coded typo lists (agent/toolrun.py) and exact-only
matching (agent/router.py). Used by router, tool binding, and teaching
detection so "turn / craete / convrt / pyton / documnet" all resolve.

Design:
- Lowercase + in-place token correction (punctuation preserved, so ".pdf"
  and "word document" still match).
- Correct only len>=4 tokens NOT in vocab, same-first-letter, len diff<=2,
  ratio>=85. Short tokens ("do/to") stay exact-only.
- Creation verbs (turn/convert/make/generate/build/...) canonicalize to
  "create" so downstream keyword lists only need the canonical.
- rapidfuzz when installed, difflib fallback. Never raises.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Sequence, Tuple

logger = logging.getLogger(__name__)

# Creation family -> canonical "create". Router/tool lists check "create".
_CREATE_VERBS = frozenset({
    "create", "make", "generate", "build", "produce", "turn",
    "convert", "prepare", "craft", "construct",
})

# Reverse map: variant -> canonical (verbs only; nouns stay as-is).
_CANONICAL: Dict[str, str] = {v: "create" for v in _CREATE_VERBS}

# Vocabulary: everything we must NOT "correct" away. Router keywords
# (cleaned), extensions, teach verbs, stopwords. Bounded, stdlib only.
_VOCAB: frozenset = frozenset({
    # router nouns/verbs
    "pdf", "read", "summarize", "summary", "document", "docx", "doc",
    "odt", "rtf", "txt", "markdown", "pptx", "ppt", "odp", "html",
    "xml", "zip", "archive", "webpage", "teach", "learn", "exam",
    "exams", "recall", "lecture", "tutor", "practice", "quiz",
    "csv", "tsv", "xlsx", "xls", "ods", "json", "analyze", "analysis",
    "spreadsheet", "dataset", "chart", "plot", "table", "python",
    "javascript", "typescript", "java", "golang", "rust", "code",
    "coding", "script", "program", "function", "debug", "traceback",
    "exception", "compile", "execute", "pytest", "npm", "node",
    "refactor", "presentation", "slides", "slide", "powerpoint",
    "essay", "report", "resume", "write", "draft", "compose",
    "letter", "export", "revise", "edit", "update", "latest",
    "recent", "current", "today", "news", "search", "find",
    "logic", "premise", "conclusion", "valid", "syllogism",
    "song", "songs", "singer", "lyrics", "lyric", "movie", "film",
    "actor", "actress", "album", "cast", "soundtrack", "released",
    "starring", "starred", "directed",
    # create family + common typo targets
    "create", "make", "generate", "build", "produce", "turn",
    "convert", "prepare", "craft", "file", "word", "into", "from",
    # teach subjects
    "page", "pages", "deck", "chapter", "topic", "lesson",
    "question", "problem", "exercise", "notes", "syllabus",
    "tutorial", "mock", "revision",
    # code/data extras
    "column", "columns", "sheet", "stats", "query", "sql",
    "database", "calendar", "event", "meeting", "invite",
    "gmail", "email", "mail",
    # stopwords (never correct these)
    "this", "that", "these", "those", "with", "please", "about",
    "hello", "thanks", "thank", "what", "when", "where", "which",
    "there", "their", "your", "yours", "mine",
})

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _ratio(a: str, b: str) -> float:
    """0-100 similarity (rapidfuzz when present, difflib fallback)."""
    try:
        from rapidfuzz import fuzz as _fuzz  # type: ignore

        return float(_fuzz.ratio(a, b))
    except Exception:
        try:
            import difflib as _difflib

            return float(_difflib.SequenceMatcher(None, a, b).ratio() * 100.0)
        except Exception:
            return 0.0 if a != b else 100.0


def _correct_token(tok: str) -> str:
    """Correct one lowercase token (never raises, exact-only for short)."""
    try:
        if not tok or len(tok) < 4 or tok in _VOCAB:
            return tok
        # Same-first-letter + len window: kills "this"->"thesis" style
        # false positives and keeps the candidate set tiny.
        cands = [
            v for v in _VOCAB
            if v and v[0] == tok[0] and abs(len(v) - len(tok)) <= 2
        ]
        best: str = tok
        best_score = 0.0
        for cand in cands:
            try:
                s = _ratio(tok, cand)
            except Exception:
                logger.debug("normalize ratio failed", exc_info=True)
                continue
            if s > best_score:
                best_score = s
                best = cand
        if best_score >= 80.0:
            return best
        return tok
    except Exception:
        return tok


def normalize_text(text: str) -> str:
    """Lowercase + typo-correct + verb-canonicalize, punctuation preserved."""
    try:
        lowered = str(text or "").lower()

        def _repl(m: re.Match) -> str:
            raw = m.group(0)
            low = raw.lower()
            fixed = _correct_token(low)
            # Verb canonicalization AFTER correction ("convrt"->"convert"->"create").
            return _CANONICAL.get(fixed, fixed)

        return _TOKEN_RE.sub(_repl, lowered)
    except Exception:
        logger.debug("normalize failed", exc_info=True)
        try:
            return str(text or "").lower()
        except Exception:
            return ""


def get_corrections(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Return (normalized, [(orig, fixed)]) for routing use. Never raises.

    NOTE: pairs include routing-internal rewrites (verb canonicalization
    such as prepare->create) and fuzzy plural/stemming maps
    (teacher->teach, questions->question). They describe what the router
    saw, not typos the user made — use get_display_corrections() for
    anything user-visible.
    """
    try:
        orig_tokens = _TOKEN_RE.findall(str(text or ""))
        norm = normalize_text(text)
        norm_tokens = _TOKEN_RE.findall(norm)
        pairs: List[Tuple[str, str]] = []
        # Align by position (normalize preserves token count/order).
        for o, n in zip(orig_tokens, norm_tokens, strict=False):
            if o.lower() != n.lower():
                pairs.append((o, n))
        return norm, pairs
    except Exception:
        return str(text or "").lower(), []


# Suffixes whose addition/removal is stemming, not a typo
# (teacher/teach, questions/question, note/notes). Such pairs must
# never render as "Interpreted X as Y" in the UI.
_DISPLAY_AFFIX_SUFFIXES = ("s", "es", "d", "ed", "er", "ing", "ly")


def _is_affix_pair(orig_lower: str, fixed: str) -> bool:
    """True when the pair differs by a bare affix (never raises)."""
    try:
        o, n = str(orig_lower or ""), str(fixed or "")
        if not o or not n or o == n:
            return False
        for suffix in _DISPLAY_AFFIX_SUFFIXES:
            if o == n + suffix or n == o + suffix:
                return True
        return False
    except Exception:
        return False


def _is_typo_shape(orig_lower: str, fixed: str) -> bool:
    """True when the pair looks like a genuine typo (never raises).

    Genuine typos are small mechanical slips: a transposition
    (craete/create), one inserted/deleted char (convrt/convert,
    pyton/python), or one substituted char (musik/music). Fuzzy
    overreach such as single->singer (two substitutions on a valid
    word) is not a typo shape. Never raises.
    """
    try:
        o, n = str(orig_lower or ""), str(fixed or "")
        if not o or not n or o == n:
            return False
        if sorted(o) == sorted(n):
            return True  # transposition / anagram
        if abs(len(o) - len(n)) == 1:
            # Single insertion/deletion: the shorter string is a
            # subsequence of the longer one with exactly one skip.
            short, long = (o, n) if len(o) < len(n) else (n, o)
            skipped = False
            i = j = 0
            while i < len(short) and j < len(long):
                if short[i] == long[j]:
                    i += 1
                    j += 1
                elif skipped:
                    return False
                else:
                    skipped = True
                    j += 1
            return True
        if len(o) == len(n):
            # Single substitution: exactly one differing position.
            return sum(1 for a, b in zip(o, n, strict=True) if a != b) == 1
        return False
    except Exception:
        return False


def _is_routing_rewrite(orig_lower: str) -> bool:
    """True when the token was rewritten by verb canonicalization.

    prepare->create and builf->build->create describe routing intent,
    not user typos — never user-visible. Never raises.
    """
    try:
        fixed = _correct_token(str(orig_lower or ""))
        return _CANONICAL.get(fixed, fixed) != fixed
    except Exception:
        return False


def get_display_corrections(text: str) -> List[Tuple[str, str]]:
    """Return [(orig, fixed)] pairs worth showing in the UI. Never raises.

    Filters get_corrections() down to probable real typos:
    - routing-internal verb canonicalizations are dropped;
    - capitalized originals are dropped (proper nouns / sentence starts
      such as "Tere", "Note" — never "corrected" away);
    - bare affix/stemming maps (teacher->teach, questions->question)
      are dropped;
    - fuzzy overreach on valid words (single->singer) is dropped: only
      typo shapes (transposition, single insert/delete/substitute)
      are shown;
    - abbreviation-collapse (text->txt) is dropped: when the "fix" only
      shortens the token into a known vocab word, the user wrote a
      valid word, not a typo. Routing still normalizes silently.
    Routing itself is untouched: normalize_text() still applies every
    rewrite above (teacher still routes teach-intent, prepare still
    routes create-intent).
    """
    try:
        # get_corrections() pairs already carry the typed original
        # (case preserved) alongside the normalized form.
        _, pairs = get_corrections(text)
        shown: List[Tuple[str, str]] = []
        for typed, n in pairs:
            try:
                if not typed or not n:
                    continue
                # Proper nouns / sentence-initial words: never "correct".
                if str(typed)[:1].isupper():
                    continue
                if _is_routing_rewrite(str(typed).lower()):
                    continue
                if _is_affix_pair(str(typed).lower(), str(n).lower()):
                    continue
                if not _is_typo_shape(str(typed).lower(), str(n).lower()):
                    continue
                if len(str(typed)) > len(str(n)) and str(n).lower() in _VOCAB:
                    continue
                shown.append((typed, n))
            except Exception:
                logger.debug("display correction filter failed", exc_info=True)
                continue
        return shown
    except Exception:
        logger.debug("display corrections failed", exc_info=True)
        return []


def fuzzy_hit(text: str, phrase: str, threshold: float = 80.0) -> bool:
    """Typo-tolerant phrase check on normalized text (never raises).

    Exact substring/whole-word first; token-level fuzzy for len>=4
    single words (mirrors toolrun heuristic, now centralized).
    """
    try:
        norm = normalize_text(text)
        p = str(phrase or "").lower().strip()
        if not p:
            return False
        # Multi-word / dotted / underscored: literal substring on normalized.
        if " " in p or "." in p or "_" in p or "[" in p:
            return p in norm
        # Stem marker.
        if p.endswith("*") and len(p) > 1:
            stem = re.escape(p[:-1])
            return re.search(r"\b" + stem + r"\w*", norm) is not None
        # Whole-word exact.
        if re.search(r"\b" + re.escape(p) + r"\b", norm) is not None:
            return True
        if len(p) < 4:
            return False
        for tok in _TOKEN_RE.findall(norm):
            if len(tok) < 4 or tok == p:
                continue
            if abs(len(tok) - len(p)) > 2:
                continue
            if tok and p and tok[0] != p[0]:
                continue
            try:
                if _ratio(tok, p) >= threshold:
                    return True
            except Exception:
                logger.debug("fuzzy ratio failed", exc_info=True)
                continue
        return False
    except Exception:
        return False


def any_hit(text: str, phrases: Sequence[str]) -> bool:
    """True when any phrase fuzzy-hits (never raises)."""
    try:
        return any(fuzzy_hit(text, p) for p in phrases)
    except Exception:
        return False
