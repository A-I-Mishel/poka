"""Turn stages: small helpers for history, meta, limits, state, approvals.

Moved verbatim from backend.flow (turn entry points live in
backend.flow.turns, the teaching stage in backend.flow.teaching).
"""

from typing import (Any, Dict, List, Optional, Tuple)
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
                     fallback: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Response metadata stored on the message (locally known facts only)."""
    meta: Dict[str, Any] = {
        "mode": "deep" if deep_mode else "fast",
        "searched": bool(searched),
    }
    if tier:
        meta["model"] = tier
    if fallback:
        meta["fallback"] = {"requested": str(fallback.get("requested", "")),
                            "reason": str(fallback.get("reason", ""))}
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
