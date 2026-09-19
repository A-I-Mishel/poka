"""Historical attachment gate: AVAILABLE vs ACTIVE separation.

Previous files stay AVAILABLE (validated history) but become ACTIVE only
when the CURRENT message explicitly refers to them or clearly needs them.
Default is deny — never auto-inject just because a file was recent.

Fast path is deterministic (0 LLM). Ambiguous pronouns use single-resource
rule, else an injected lightweight classifier; failures deny safely.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from agent.router import _signals

logger = logging.getLogger(__name__)

VISION_NOUNS = (
    "image", "images", "photo", "photos", "picture", "pictures", "pic",
    "screenshot", "screenshots", "scan", "scanned", "what do you see",
)
DOC_NOUNS = (
    "pdf", "document", "documents", "docx", "doc", "docs", "word",
    "pptx", "ppt", "powerpoint",
    "presentation", "deck", "slides", "slide", "spreadsheet", "csv",
)
VISION_EXPLICIT = (
    "this image", "that image", "the image", "this photo", "the photo",
    "that photo", "this screenshot", "the screenshot", "that screenshot",
    "this picture", "the picture", "that picture", "this pic", "the pic",
)
DOC_EXPLICIT = (
    "this pdf", "the pdf", "that pdf", "this document", "the document",
    "that document", "this ppt", "the ppt", "that ppt",
    "this presentation", "the presentation", "that presentation",
    "this file", "that file", "the file", "the deck",
)
# New-topic signals detected semantically (song/music/code/search), never a
# hardcoded user phrase. Bare "tere liye" alone means nothing; "song" is the
# music intent that denies file reuse.
NEW_INTENT_SIGNALS = (
    "song", "songs", "gana", "gaana", "lyrics", "lyric", "music",
    "singer", "sunao", "play the", "python", "code", "coding", "function",
    "debug", "script", "program", "algorithm", "latest", "news", "weather",
)
AMBIGUOUS_PHRASES = (
    "what is this", "what's this", "what is that", "what's that",
    "what about that", "explain this", "explain that", "summarize this",
    "summarise this", "describe this", "tell me about this", "what is it",
    "what does it say", "isme", "usme", "ispe", "uspe", "is mein",
    "us mein", "yeh kya", "ye kya", "kya hai", "kya likha", "kya dikh",
)
# Short teaching continuations ("continue", "next") reuse available files.
# ponytail: whole intent class, never a hardcoded user phrase; NEW_INTENT
# above still wins ("next song" stays a song, never a file).
CONTINUATION_SIGNALS = (
    "continu*", "next", "proceed", "go on", "go ahead",
    "keep going", "carry on", "remain*", "finish*", "complet*",
)
_PRONOUNS = ("this", "that", "it", "isme", "usme", "ispe", "yeh", "ye")
_SLIDE_RE = re.compile(r"\bslides?\s*\d+")
_PAGE_RE = re.compile(r"\bpages?\s*\d+")
_PPT_EXT_RE = re.compile(r"\.(pptx?|odp)\s*$", re.IGNORECASE)

CLARIFY_TEXT = "Are you referring to the image, PDF, or presentation?"


def _stem(name: str) -> str:
    base = os.path.basename(str(name or ""))
    stem, _ = os.path.splitext(base)
    return stem.strip().lower()


def _filename_hits(text: str, entries: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for e in entries:
        name = str(e.get("name", "") or "").lower()
        if len(name) < 4 or name not in text:
            stem = _stem(str(e.get("name", "")))
            if len(stem) < 4 or stem not in text:
                continue
        hits.append(e)
    return hits


def decide(
    text: str,
    images: Sequence[Dict[str, Any]],
    docs: Sequence[Dict[str, Any]],
    classifier: Optional[Callable[[str, List[str]], Tuple[str, float]]] = None,
) -> Dict[str, Any]:
    """Decide which historical attachments become ACTIVE.

    Returns {"use_images": [...], "use_docs": [...], "clarify": None|str,
    "reason": str}. Never raises; failures deny safely.
    """
    try:
        t = str(text or "").lower().strip()
        imgs = [dict(e) for e in (images or []) if isinstance(e, dict) and e.get("id")]
        dcs = [dict(e) for e in (docs or []) if isinstance(e, dict) and e.get("id")]
        if not t:
            return {"use_images": [], "use_docs": [], "clarify": None, "reason": "empty"}

        # 1. Explicit filename wins, only the named files.
        all_avail = imgs + dcs
        if all_avail:
            named = _filename_hits(t, all_avail)
            if named:
                img_ids = {x.get("id") for x in imgs}
                use_i = [e for e in named if e.get("id") in img_ids]
                use_d = [e for e in named if e.get("id") not in img_ids]
                return {"use_images": use_i, "use_docs": use_d,
                        "clarify": None, "reason": "filename"}

        # 2. Slide/page number selects presentation/document only (most recent).
        if _SLIDE_RE.search(t) and dcs:
            ppts = [e for e in dcs if _PPT_EXT_RE.search(str(e.get("name", "")))]
            picked = (ppts or list(dcs))[-1:]
            return {"use_images": [], "use_docs": picked,
                    "clarify": None, "reason": "slide-number"}
        if _PAGE_RE.search(t) and dcs:
            return {"use_images": [], "use_docs": list(dcs)[-1:],
                    "clarify": None, "reason": "page-number"}

        # 3. Explicit type phrases.
        has_vexp = _signals(t, VISION_EXPLICIT)
        has_dexp = _signals(t, DOC_EXPLICIT)
        if has_vexp or has_dexp:
            use_i = list(imgs) if has_vexp else []
            use_d = list(dcs) if has_dexp else []
            if has_vexp and has_dexp:
                use_i, use_d = list(imgs), list(dcs)
            return {"use_images": use_i, "use_docs": use_d,
                    "clarify": None, "reason": "explicit-type"}

        # 4. Clear current intent via attachment-type nouns.
        has_v = _signals(t, VISION_NOUNS)
        has_d = _signals(t, DOC_NOUNS) or _SLIDE_RE.search(t) is not None or _PAGE_RE.search(t) is not None
        if has_v and not has_d:
            return {"use_images": list(imgs), "use_docs": [],
                    "clarify": None, "reason": "vision-intent"}
        if has_d and not has_v:
            return {"use_images": [], "use_docs": list(dcs),
                    "clarify": None, "reason": "document-intent"}
        if has_v and has_d:
            return {"use_images": list(imgs), "use_docs": list(dcs),
                    "clarify": None, "reason": "both-intents"}

        # 5. New-topic semantic intent (song/music/code/search) denies files.
        # ponytail: general intent nouns only, never a hardcoded user phrase;
        # extend only when a whole intent class misfires.
        if _signals(t, NEW_INTENT_SIGNALS):
            return {"use_images": [], "use_docs": [], "clarify": None,
                    "reason": "new-intent"}

        # 5b. Short continuation reuses most-recent file so "continue" /
        # "next" after a long doc answer keeps teaching instead of
        # restarting blind. Length-guarded: long new questions that
        # happen to contain "next" stay default-deny.
        if len(t) <= 80 and (imgs or dcs) and _signals(t, CONTINUATION_SIGNALS):
            return {"use_images": list(imgs)[-1:], "use_docs": list(dcs)[-1:],
                    "clarify": None, "reason": "continuation"}

        # 6. Ambiguous pronoun reference.
        ambiguous = _signals(t, AMBIGUOUS_PHRASES) or (
            len(t) <= 60 and _signals(t, _PRONOUNS)
        )
        if ambiguous:
            if imgs and not dcs:
                return {"use_images": list(imgs)[-1:], "use_docs": [],
                        "clarify": None, "reason": "ambiguous-single-image"}
            if dcs and not imgs:
                return {"use_images": [], "use_docs": list(dcs)[-1:],
                        "clarify": None, "reason": "ambiguous-single-doc"}
            if not imgs and not dcs:
                return {"use_images": [], "use_docs": [], "clarify": None,
                        "reason": "ambiguous-none-available"}
            # Both modalities: try LLM classifier, else clarify.
            if classifier is not None:
                try:
                    kinds = ["image"] if imgs else []
                    kinds += ["document"] if any(
                        not _PPT_EXT_RE.search(str(e.get("name", ""))) for e in dcs) else []
                    kinds += ["presentation"] if any(
                        _PPT_EXT_RE.search(str(e.get("name", ""))) for e in dcs) else []
                    intent, conf = classifier(t, kinds)
                    intent = str(intent or "").lower()
                    conf = float(conf or 0.0)
                    if conf >= 0.7 and intent == "vision":
                        return {"use_images": list(imgs), "use_docs": [],
                                "clarify": None, "reason": "llm-vision"}
                    if conf >= 0.7 and intent == "presentation":
                        ppts = [e for e in dcs if _PPT_EXT_RE.search(str(e.get("name", "")))]
                        return {"use_images": [], "use_docs": ppts or list(dcs),
                                "clarify": None, "reason": "llm-presentation"}
                    if conf >= 0.7 and intent == "document":
                        return {"use_images": [], "use_docs": list(dcs),
                                "clarify": None, "reason": "llm-document"}
                    if conf >= 0.7 and intent in ("web", "none"):
                        return {"use_images": [], "use_docs": [], "clarify": None,
                                "reason": "llm-none"}
                except Exception:
                    logger.debug("llm gate classifier failed; asking user", exc_info=True)
            return {"use_images": [], "use_docs": [], "clarify": CLARIFY_TEXT,
                    "reason": "ambiguous-multi-clarify"}

        # 7. No reference: default deny.
        return {"use_images": [], "use_docs": [], "clarify": None,
                "reason": "no-reference"}
    except Exception:
        return {"use_images": [], "use_docs": [], "clarify": None,
                "reason": "gate-error-deny"}
