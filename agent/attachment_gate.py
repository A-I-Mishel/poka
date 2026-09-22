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
    # Exam-paper phrases (multi-word: substring match on normalized text,
    # so "quesylon paper" still hits after typo correction). Bare "paper"
    # stays OUT deliberately: "write a paper" is an essay request, not a
    # file reference.
    "question paper", "exam paper", "test paper", "q paper",
)
# Past-upload reference ("the question paper i uploaded", "the file i
# uploaded"): the user points at history, not a new topic. Checked AFTER
# new-topic intents so "play the song i uploaded" stays music.
PAST_UPLOAD_SIGNALS = (
    "i uploaded", "my upload", "uploaded file", "uploaded paper",
    "uploaded image", "uploaded photo", "uploaded pdf", "uploaded doc",
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

# Image-thread follow-ups: dispute or drill into the previous answer
# ("I think ii) is c", "are you sure?", "why?", "explain q2").
# These carry no image nouns/pronouns, so decide() default-denies them —
# yet they reference shared Q&A context established by a recent image
# (the 10:41 "I think ii) is c" turn asked Groq about option texts it
# never received). Length-guarded like continuations; new-topic intents
# always win; recency window keeps old images out.
_IMAGE_FOLLOWUP_DISPUTE = (
    "i think", "are you sure", "is that right", "r u sure",
    "wrong", "incorrect", "actually", "but ", "no,",
    "why", "explain",
)
_IMAGE_FOLLOWUP_OPTION_RE = re.compile(
    r"\b[ivx]{1,4}\)|\boption\s+[a-d]\b|\bq\s*\d+|\bquestion\s+(?:[ivx]{1,4}|\d+)",
    re.IGNORECASE,
)
_IMAGE_FOLLOWUP_MAX_CHARS: int = 160
_IMAGE_FOLLOWUP_WINDOW: int = 4


def _history_image_ids(history: Sequence[Dict[str, Any]],
                       window: int = _IMAGE_FOLLOWUP_WINDOW) -> List[str]:
    """Upload IDs of images in recent user messages, oldest first."""
    found: List[str] = []
    try:
        recent = list(history or [])[-max(1, int(window)):]
        for m in recent:
            if not isinstance(m, dict):
                continue
            if str(m.get("role", "") or "").lower() != "user":
                continue
            atts = m.get("attachments")
            if isinstance(atts, list):
                for a in atts:
                    if (isinstance(a, dict) and a.get("kind") == "image"
                            and a.get("id") and a["id"] not in found):
                        found.append(str(a["id"]))
            for key in ("image", "images"):
                val = m.get(key)
                items = val if isinstance(val, list) else [val]
                for v in items:
                    if v and str(v) not in found:
                        found.append(str(v))
    except Exception:
        logger.debug("history image scan failed", exc_info=True)
    return found


def is_image_followup(text: str, history: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Most-recent image ID when text disputes/drills the image thread.

    Returns None for new-topic intents, stale images (outside the
    recency window), and long messages (likely new questions that
    happen to contain "why"). Never raises.
    """
    try:
        t = str(text or "").lower().strip()
        if not t or len(t) > _IMAGE_FOLLOWUP_MAX_CHARS:
            return None
        if _signals(t, NEW_INTENT_SIGNALS):
            return None
        option_ref = _IMAGE_FOLLOWUP_OPTION_RE.search(t) is not None
        dispute = _signals(t, _IMAGE_FOLLOWUP_DISPUTE)
        if not (option_ref or dispute):
            return None
        recent = _history_image_ids(history)
        return recent[-1] if recent else None
    except Exception:
        logger.debug("image followup check failed", exc_info=True)
        return None


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

        # 3. Explicit type phrases. Users name modalities loosely
        # ("photo" for a scanned PDF is the norm in student chats), so an
        # explicitly named but empty side falls back to the most recent
        # file of the other side instead of denying. Filenames (step 1)
        # and slide/page numbers (step 2) stay strict: those are precise.
        has_vexp = _signals(t, VISION_EXPLICIT)
        has_dexp = _signals(t, DOC_EXPLICIT)
        if has_vexp or has_dexp:
            use_i = list(imgs) if has_vexp else []
            use_d = list(dcs) if has_dexp else []
            if has_vexp and has_dexp:
                use_i, use_d = list(imgs), list(dcs)
            if not use_i and not use_d:
                if has_vexp and dcs:
                    return {"use_images": [], "use_docs": list(dcs)[-1:],
                            "clarify": None, "reason": "explicit-vision-fallback-doc"}
                if has_dexp and imgs:
                    return {"use_images": list(imgs)[-1:], "use_docs": [],
                            "clarify": None, "reason": "explicit-doc-fallback-image"}
            return {"use_images": use_i, "use_docs": use_d,
                    "clarify": None, "reason": "explicit-type"}

        # 4. Clear current intent via attachment-type nouns.
        # Cross-modality fallback: noun-level intent ("paper", "photo")
        # is approximate — a photographed question paper IS the image.
        # When the named side is empty but the other side has files,
        # reuse the most recent one instead of denying (the 12:19
        # "whole question paper" turn asked about a photo). Explicit
        # type phrases (step 3) and filenames (step 1) stay strict.
        has_v = _signals(t, VISION_NOUNS)
        has_d = _signals(t, DOC_NOUNS) or _SLIDE_RE.search(t) is not None or _PAGE_RE.search(t) is not None
        if has_v and not has_d:
            if imgs:
                return {"use_images": list(imgs), "use_docs": [],
                        "clarify": None, "reason": "vision-intent"}
            if dcs:
                return {"use_images": [], "use_docs": list(dcs)[-1:],
                        "clarify": None, "reason": "vision-intent-fallback-doc"}
        if has_d and not has_v:
            if dcs:
                return {"use_images": [], "use_docs": list(dcs),
                        "clarify": None, "reason": "document-intent"}
            if imgs:
                return {"use_images": list(imgs)[-1:], "use_docs": [],
                        "clarify": None, "reason": "document-intent-fallback-image"}
        if has_v and has_d:
            return {"use_images": list(imgs), "use_docs": list(dcs),
                    "clarify": None, "reason": "both-intents"}

        # 5. New-topic semantic intent (song/music/code/search) denies files.
        # ponytail: general intent nouns only, never a hardcoded user phrase;
        # extend only when a whole intent class misfires.
        if _signals(t, NEW_INTENT_SIGNALS):
            return {"use_images": [], "use_docs": [], "clarify": None,
                    "reason": "new-intent"}

        # 5b. Past-upload reference ("do you have info on the paper i
        # uploaded"): requires a modality noun alongside the past-upload
        # signal ("that PDF I uploaded", "that image I uploaded"). Vague
        # "that thing I uploaded" without a noun stays default-deny so a
        # stale file from 5 turns ago is not auto-activated. Single
        # available modality reuses its most recent file; both modalities
        # clarify (fail-closed, like ambiguous-multi).
        # Note: bare "paper" counts as a doc noun ONLY here (past-upload
        # disambiguates essay "write a paper" vs file "paper I uploaded";
        # see test_paper_reuse.py). Typo "quesylon paper" still hits via
        # the "paper" substring.
        if (imgs or dcs) and _signals(t, PAST_UPLOAD_SIGNALS):
            _has_v = _signals(t, VISION_NOUNS) or _signals(t, VISION_EXPLICIT)
            _has_d = _signals(t, DOC_NOUNS) or _signals(t, DOC_EXPLICIT) or _SLIDE_RE.search(t) is not None or _PAGE_RE.search(t) is not None or ("paper" in t)
            if not (_has_v or _has_d):
                pass  # fall through to continuation/ambiguous/default-deny
            elif imgs and not dcs:
                return {"use_images": list(imgs)[-1:], "use_docs": [],
                        "clarify": None, "reason": "past-upload-image"}
            elif dcs and not imgs:
                return {"use_images": [], "use_docs": list(dcs)[-1:],
                        "clarify": None, "reason": "past-upload-doc"}
            else:
                return {"use_images": [], "use_docs": [],
                        "clarify": CLARIFY_TEXT, "reason": "past-upload-clarify"}

        # 5c. Short continuation reuses most-recent file so "continue" /
        # "next" after a long doc answer keeps teaching instead of
        # restarting blind. Length-guarded + noun-guarded: bare "continue"
        # without a file noun is handled by the teaching session flag
        # (teach.py) and stays default-deny here to avoid stale activation.
        # Long new questions that happen to contain "next" stay deny.
        if len(t) <= 80 and (imgs or dcs) and _signals(t, CONTINUATION_SIGNALS):
            _has_vc = _signals(t, VISION_NOUNS) or _signals(t, VISION_EXPLICIT)
            _has_dc = _signals(t, DOC_NOUNS) or _signals(t, DOC_EXPLICIT) or _SLIDE_RE.search(t) is not None or _PAGE_RE.search(t) is not None
            if _has_vc or _has_dc:
                # Only return the side whose noun fired, not both.
                if _has_vc and not _has_dc and imgs:
                    return {"use_images": list(imgs)[-1:], "use_docs": [],
                            "clarify": None, "reason": "continuation"}
                if _has_dc and not _has_vc and dcs:
                    return {"use_images": [], "use_docs": list(dcs)[-1:],
                            "clarify": None, "reason": "continuation"}
                return {"use_images": list(imgs)[-1:], "use_docs": list(dcs)[-1:],
                        "clarify": None, "reason": "continuation"}
            # No noun → fall through to ambiguous/default-deny; teaching
            # continuation is owned by teach.py flag+recency, not the gate.

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

        # 6b. Past-upload reference with nothing in THIS conversation:
        # files stay with the chat they were uploaded in, so "the paper
        # i uploaded" in a fresh chat cannot resolve. Say exactly that
        # instead of a generic deny (which reads as "re-upload blindly").
        if _signals(t, PAST_UPLOAD_SIGNALS):
            return {"use_images": [], "use_docs": [],
                    "clarify": ("I don't see that upload in this conversation — "
                                "files stay with the chat they were uploaded in. "
                                "Please re-upload it here (or share its upload ID) "
                                "and I'll read it right away."),
                    "reason": "past-upload-none"}

        # 7. No reference: default deny.
        return {"use_images": [], "use_docs": [], "clarify": None,
                "reason": "no-reference"}
    except Exception:
        return {"use_images": [], "use_docs": [], "clarify": None,
                "reason": "gate-error-deny"}
