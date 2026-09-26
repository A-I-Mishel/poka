"""Turn stages: small helpers for history, meta, limits, state, approvals.

Moved verbatim from backend.flow (turn entry points live in
backend.flow.turns, the teaching stage in backend.flow.teaching).
"""

from typing import (Any, Dict, List, Optional, Tuple)

import re
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter
from services.storage import StorageError, clean_source_record
from backend.deps import UserContext

from backend.attachments import (_recent_document_attachments, _recent_image_ids)


_IDENTITY_QUESTION_RES = None


def _identity_patterns():
    """Compiled identity-about-user patterns (built once, never raises)."""
    global _IDENTITY_QUESTION_RES
    try:
        if _IDENTITY_QUESTION_RES is None:
            import re as _re

            _IDENTITY_QUESTION_RES = tuple(
                _re.compile(p) for p in (
                    r"who am i",
                    r"what(?:'s| is|s| s) my name",
                    # Reported gap: "do you know what is my name?" never
                    # matched "do you know my name". Optional what-is
                    # prefix + who-am-i / me variants, fullmatch only so
                    # "who am i in this essay" still misses.
                    r"do (?:you|u) know (?:what(?:'s| is|s| s) )?(?:my name|who am i|who i am|me)",
                    r"what do you call me",
                    r"tell me my name",
                ))
        return _IDENTITY_QUESTION_RES
    except Exception:
        return ()


_GREETING_PREFIX_RES = None


# Pure-greeting fast path (zero model calls): the highest-frequency,
# lowest-value turns ("hi", "hello") skip the cascade entirely.
# Full-match ONLY on bare greetings — "hi, what is a vertex?" still
# takes the model path. Evaluated AFTER sticky continuations in turns.py
# (a mid-teaching "hi" is a session ack, never a greeting). Any doubt
# fails open to the model. Kill-switch: PLUTO_GREETINGS=0.
_PURE_GREETINGS = frozenset({
    "hi", "hii", "hiii", "hello", "helloo", "hey", "heyy",
    "yo", "sup", "howdy", "greetings",
    "good morning", "good afternoon", "good evening",
    "salam", "assalamualaikum", "assalamu alaikum",
})

_GREETING_REPLIES = (
    "Hey! Good to see you — what are we working on?",
    "Hi there! What's on your mind?",
    "Hello! Ready when you are — what's up?",
)

_SALAM_REPLIES = (
    "Walaikum assalam! How can I help you today?",
    "Walaikum assalam! What are we working on?",
)


def _is_pure_greeting(text: Any) -> bool:
    """True when the message is ONLY a greeting (never raises)."""
    try:
        import re as _re

        normalized = str(text or "").lower()
        normalized = _re.sub(r"[!?.\u2026,]+", " ", normalized)
        normalized = _re.sub(r"\s+", " ", normalized).strip()
        if not normalized or len(normalized) > 30:
            return False
        return normalized in _PURE_GREETINGS
    except Exception:
        return False


def _greeting_reply(text: Any, user_id: Any = "") -> str:
    """Deterministic rotating greeting reply (never raises).

    Rotation is a stable hash of user + day: same user sees variety
    across days without per-turn randomness to test. Salam greetings
    get salam replies; everything else shares the standard set.
    """
    try:
        import hashlib as _hl

        normalized = str(text or "").lower()
        pool = _SALAM_REPLIES if "salam" in normalized else _GREETING_REPLIES
        try:
            import datetime as _dt

            day = _dt.date.today().isoformat()
        except Exception:
            day = ""
        digest = _hl.sha256(f"{user_id or ''}:{day}".encode()).digest()
        return pool[digest[0] % len(pool)]
    except Exception:
        return _GREETING_REPLIES[0]


def _greetings_enabled() -> bool:
    """False when the operator disables the zero-call greeting path."""
    try:
        from services.secrets import get_secret as _get_secret

        return (_get_secret("PLUTO_GREETINGS", "1") or "1").strip().lower() not in (
            "0", "false", "no", "off")
    except Exception:
        return True


# Fabricated-file backstop: a weak tier asked for a file deliverable
# may paste a fake truncated base64 blob with decode-it-yourself
# instructions and a phantom-attachment reference instead of using a
# file tool. All three markers must match (conjunction), and a real
# download ID exempts the turn — ordinary code answers containing
# base64 never trip it.
_FAKE_FILE_RES = (
    re.compile(r"truncated for brevity", re.IGNORECASE),
    re.compile(r"base64(?:\s|$|[.\-])|base64\s*-d|b64decode",
               re.IGNORECASE),
    re.compile(r"attach", re.IGNORECASE),
)
_REAL_DOWNLOAD_RE = re.compile(r"\(file ID:\s*[0-9a-f]{8,}\)", re.IGNORECASE)

_FAKE_FILE_FALLBACK = (
    "I can't assemble that file here — use the Export PDF download "
    "in this chat for the full transcript."
)


def _is_fabricated_file(text: Any) -> bool:
    """True for fake-file payloads (never raises)."""
    try:
        body = str(text or "")
        if not body or len(body) < 200:
            return False
        if _REAL_DOWNLOAD_RE.search(body):
            return False
        return all(rx.search(body) for rx in _FAKE_FILE_RES)
    except Exception:
        return False


# Exact-repeat cache (opt-in): identical questions answered twice in a
# row cost the full 4-8 call pipeline twice. A short-TTL cache keyed
# on (user, normalized text, deep_mode, pinned tier) reuses the last
# answer with zero calls. OFF by default (PLUTO_REPEAT_CACHE=1 to try):
# same words can deserve a fresh answer when files, teaching cursor,
# or memory changed — callers must exclude teaching/vision/attachment
# turns and only store clean (no-fallback, no-approval) answers.
# Hits are metered (obs "repeat_cache.hit") so the trial reads out.
_REPEAT_CACHE_TTL_S = 300.0
_REPEAT_CACHE_MAX = 64
_repeat_cache: Dict[str, tuple] = {}


def _repeat_cache_enabled() -> bool:
    """True only when the operator opts into the repeat-answer trial."""
    try:
        from services.secrets import get_secret as _get_secret

        return (_get_secret("PLUTO_REPEAT_CACHE", "0") or "0").strip().lower() in (
            "1", "true", "yes", "on")
    except Exception:
        return False


def _repeat_cache_key(text: Any, user_id: Any = "",
                      deep_mode: bool = False,
                      pinned_tier: Any = "") -> str:
    """Cache key for one repeatable turn (never raises)."""
    try:
        import hashlib as _hl
        import re as _re

        normalized = _re.sub(r"\s+", " ", str(text or "").lower()).strip()
        raw = f"{user_id or ''}\n{normalized}\n{bool(deep_mode)}\n{pinned_tier or ''}"
        return _hl.sha256(raw.encode()).hexdigest()
    except Exception:
        return ""


def _repeat_cache_get(key: str) -> Optional[Dict[str, Any]]:
    """Fresh cached answer or None (never raises; prunes expired)."""
    try:
        import time as _time

        if not key:
            return None
        now = _time.time()
        hit = _repeat_cache.get(key)
        if hit is None:
            return None
        ts, value = hit
        if now - float(ts) > _REPEAT_CACHE_TTL_S:
            _repeat_cache.pop(key, None)
            return None
        return dict(value) if isinstance(value, dict) else None
    except Exception:
        return None


def _repeat_cache_put(key: str, value: Dict[str, Any]) -> None:
    """Store one clean answer (never raises; bounded)."""
    import logging as _logging

    try:
        import time as _time

        if not key or not isinstance(value, dict):
            return
        while len(_repeat_cache) >= _REPEAT_CACHE_MAX:
            _repeat_cache.pop(next(iter(_repeat_cache)))
        _repeat_cache[key] = (_time.time(), dict(value))
    except Exception:
        _logging.getLogger(__name__).debug(
            "repeat-cache store failed", exc_info=True)


def _is_user_identity_question(text: Any) -> bool:
    """True when the message IS a user-identity question (never raises).

    Full-match only (after an optional greeting): "who am i" qualifies,
    "who am i in this essay" does not. "who are you" / "what is your
    name" (about Pluto) never match — different pronouns, different
    patterns. Narrow by design; the model still handles everything else.
    """
    try:
        import re as _re

        global _GREETING_PREFIX_RES
        if _GREETING_PREFIX_RES is None:
            _GREETING_PREFIX_RES = _re.compile(
                r"^(?:hi|hey|hello|ok|okay|so|please)[, ]+", _re.IGNORECASE)
        normalized = str(text or "").lower()
        normalized = _re.sub(r"[?!.\u2026]+", " ", normalized)
        normalized = _re.sub(r"\s+", " ", normalized).strip()
        if not normalized or len(normalized) > 60:
            return False
        normalized = _GREETING_PREFIX_RES.sub("", normalized).strip()
        if not normalized:
            return False
        return any(p.fullmatch(normalized) for p in _identity_patterns())
    except Exception:
        return False


def _stored_user_name_or_none(ctx: UserContext) -> Optional[str]:
    """Stored user name, or None when unknown/unreadable (never raises).

    Binds the request user first (memory is per-user vault state); any
    failure falls through to None so the turn takes the normal model
    path instead of answering from a blank vault.
    """
    try:
        from backend.deps import bind_request_user as _bind

        try:
            _bind(ctx.user_id, ctx.limit_key or ctx.user_id, ctx.source or "")
        except Exception:
            return None
        from services.memory import load_structured_memory

        name = load_structured_memory().get("user_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None
    except Exception:
        return None


def build_chat_history(messages: List[Dict[str, Any]]) -> List[BaseMessage]:
    """Convert stored messages to LangChain history (content only).

    Untrimmed by design: history shaping (summarize vs verbatim) is
    owned entirely by agent.runtime, which sees the raw conversation.
    This list is only a fallback when shaping fails, so trimming here
    would silently discard context the runtime could have used.
    """
    history: List[BaseMessage] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content", ""))
        if msg.get("role") == "user":
            history.append(HumanMessage(content=content))
        else:
            history.append(AIMessage(content=content))
    return history


def _assistant_meta(tools_used: List[str], sources: List[Dict[str, str]],
                     searched: bool, deep_mode: bool, tier: str,
                     fallback: Optional[Dict[str, str]] = None,
                     teaching: Optional[Dict[str, Any]] = None,
                     *, awaiting: str) -> Dict[str, Any]:
    """Response metadata stored on the message (locally known facts only).

    `awaiting` is REQUIRED (keyword-only, no default): every assistant-turn
    writer must state what Pluto is waiting on the user to respond to
    ("teaching:{file}:{cursor}", "none", or "ambiguous:..." — the latter
    produced ONLY by _awaiting_for_turn in turns.py). There is no valid
    "I don't know": pass "none". Forgetting it is a TypeError, not a
    silent stale pointer.
    """
    meta: Dict[str, Any] = {
        "mode": "deep" if deep_mode else "fast",
        "searched": bool(searched),
    }
    if tier:
        meta["model"] = tier
    if fallback:
        meta["fallback"] = {"requested": str(fallback.get("requested", "")),
                            "reason": str(fallback.get("reason", ""))}
    # Explicit teaching session cursor — session boundary does not rely
    # solely on 📘 FILE: header scan. Validated + capped at write time;
    # cleaners.py whitelists the same shape on reload.
    # Always-emit: every turn stores the teaching dict (active or not) so
    # readers never branch on missing-vs-False. Non-teaching turns stamp
    # active:False with the current awaiting pointer.
    _awaiting = str(awaiting or "none")[:160] or "none"
    if isinstance(teaching, dict) and teaching.get("active") is True:
        try:
            _cursor = max(0, int(teaching.get("cursor", 0)))
        except Exception:
            _cursor = 0
        meta["teaching"] = {
            "active": True,
            "file": str(teaching.get("file", "") or "")[:120],
            "cursor": _cursor,
            "awaiting": str(teaching.get("awaiting", "") or _awaiting)[:160] or "none",
            "v": 1,
        }
    else:
        meta["teaching"] = {
            "active": False,
            "file": "",
            "cursor": 0,
            "awaiting": _awaiting,
            "v": 1,
        }
    names = [t for t in tools_used if isinstance(t, str) and t]
    meta["search_executed"] = "web_search" in names
    if names:
        meta["tools"] = names
    records = [dict(s) for s in sources if isinstance(s, dict)]
    if records:
        meta["sources"] = records
    return meta


def _fallback_info(requested: Optional[str], actual: str) -> Optional[Dict[str, str]]:
    """Describe a cascade fallback for ANY tier pair (or None).

    When the answering tier differs from the requested preference, name
    the reason from the requested tier's last classified failure
    (rate-limited, timed out, ...). Unknown tiers / no fallback -> None.
    """
    want = str(requested or "").strip()
    got = str(actual or "").strip()
    if not want or not got or want == got:
        return None
    try:
        from agent.cascade import _friendly_reason, last_tier_error

        hit = last_tier_error(want)
        reason = _friendly_reason(hit[0]) if hit else "unavailable"
    except Exception:
        reason = "unavailable"
    return {"requested": want, "reason": reason}


def _clean_sources(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Re-validate provenance records; http(s) only, capped at 6."""
    clean: List[Dict[str, str]] = []
    for entry in records or []:
        cleaned = clean_source_record(entry)
        if cleaned is not None:
            clean.append(cleaned)
        if len(clean) >= 6:
            break
    return clean


def _available_for_gate(ctx: UserContext,
                        messages: List[Any]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """AVAILABLE (not ACTIVE) history for the attachment gate (never raises)."""
    try:
        image_ids = _recent_image_ids(ctx, messages, [])
    except Exception:
        image_ids = []
    images: List[Dict[str, str]] = []
    for uid in image_ids or []:
        try:
            meta = ctx.file_store.get_upload(str(uid))
            name = str(getattr(meta, "display_name", "image") or "image")
        except Exception:
            name = "image"
        images.append({"id": str(uid), "kind": "image", "name": name})
    try:
        docs = _recent_document_attachments(ctx, messages, [])
    except Exception:
        docs = []
    return images, [dict(d) for d in (docs or []) if isinstance(d, dict)]


def _attachment_classifier(active_tier: Optional[str]):
    """Cascade-backed (intent, confidence) callable for ambiguous pronouns."""
    def _fn(text: str, kinds: List[str]):
        from agent.cascade import _run_cascade_step
        from agent.router import classify_attachment_need

        def _call(_name, llm):
            return classify_attachment_need(str(text), list(kinds or []), llm, budget=None)

        _tier, result = _run_cascade_step(_call, first=(active_tier or None))
        return result
    return _fn


def _check_limits(limit_key: str, deep_mode: bool) -> None:
    """Enforce chat (+deep) rate limits; raises HTTPException(429)."""
    from fastapi import HTTPException

    from services.ratelimit import rate_limit_headers

    verdict = get_rate_limiter().check(limit_key, "chat")
    if not verdict.allowed:
        obs_event("ratelimit.deny", action="chat", user=limit_key,
                  retry_after_s=round(verdict.retry_after, 1))
        raise HTTPException(
            status_code=429,
            detail=f"Chat rate limit exceeded, retry in {verdict.retry_after:.0f}s.",
            headers=rate_limit_headers(verdict, "chat"),
        )
    if deep_mode:
        deep_verdict = get_rate_limiter().check(limit_key, "deep")
        if not deep_verdict.allowed:
            obs_event("ratelimit.deny", action="deep", user=limit_key,
                      retry_after_s=round(deep_verdict.retry_after, 1))
            raise HTTPException(
                status_code=429,
                detail=f"Deep Mode rate limit exceeded, retry in {deep_verdict.retry_after:.0f}s.",
                headers=rate_limit_headers(deep_verdict, "deep"),
            )


def _load_state(store: Any) -> Tuple[List[Any], List[Any], List[str]]:
    """Load (chats, current, warnings), tolerating storage trouble."""
    try:
        stored, warnings = store.load_chats()
    except StorageError:
        stored, warnings = {"chats": [], "current": []}, []
    chats = stored.get("chats", []) if isinstance(stored, dict) else []
    current = stored.get("current", []) if isinstance(stored, dict) else []
    if not isinstance(chats, list):
        chats = []
    if not isinstance(current, list):
        current = []
    return chats, current, [str(w) for w in warnings]


def _memory_and_project(store: Any, project_id: Optional[str]) -> Tuple[str, str]:
    """Load memory notes + project context, tolerating storage trouble."""
    try:
        memory_notes = store.load_notes()
    except StorageError:
        obs_event("chatflow.memory", status="degraded", reason="memory-unavailable")
        memory_notes = ""
    project_context = ""
    if isinstance(project_id, str) and project_id:
        try:
            project_context = store.load_project_context(project_id)
        except Exception:
            obs_event("chatflow.memory", status="degraded", reason="project-unavailable")
            project_context = ""
    return memory_notes, project_context


def _turn_approvals(ctx: UserContext) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Pending approvals for a turn response (never raises).

    Returns (persisted, live): persisted holds id/tool/summary only (safe
    for chat history — tokens must never reach model context); live holds
    the same plus single-use tokens for immediate UI delivery.
    """
    try:
        from services import approvals as approvals_svc

        live = approvals_svc.list_pending(ctx.user_id, rotate_tokens=True)
        persisted = [{k: a.get(k, "") for k in ("id", "tool", "summary")}
                     for a in live]
        return persisted, live
    except Exception:
        return [], []
