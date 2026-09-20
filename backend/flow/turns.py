"""Turn entry points: run_chat / regenerate_chat plus completion plumbing.

Moved verbatim from backend.flow. Stage helpers live in
backend.flow.stages, the teaching stage in backend.flow.teaching.
"""

from typing import (Any, Dict, List, Optional, Tuple)
import logging
from fastapi import HTTPException
from langchain_core.messages import BaseMessage, HumanMessage
import agent
from agent.budget import BudgetExhausted, TurnCancelled
from agent.executor import ExecutorBusyError
from services.limits import MAX_CHAT_TITLE_CHARS, MAX_DISPLAY_NAME_CHARS
from services.storage import (is_valid_id, new_conversation_id)
from services.timeutil import utcnow_iso
from services.storage.io import path_lock as _chats_path_lock
from backend.deps import UserContext

from backend.attachments import (_attachment_text_hint, _resolve_attachments, attachment_hint, attachments_overview)
from backend.flow.stages import (_assistant_meta, _attachment_classifier, _available_for_gate, _check_limits, _clean_sources, _fallback_info, _load_state, _memory_and_project, _turn_approvals, build_chat_history)
from backend.flow.teaching import _apply_teaching_session
from backend.teach import (_is_pace_feedback, _is_teaching_continuation, _is_teaching_request, _log_teaching_format, _maybe_repair_teaching_turn)

logger = logging.getLogger(__name__)


# Identical-text in-flight guard: a client retry/abort-resend of the same
# message while its first turn is still generating must not launch a
# second full turn (double quota burn + duplicate answers, e.g. two
# "teach me slide by slide" answers minutes apart). Keyed per chat file
# + normalized text; entries are released in run_chat's finally and
# expire via TTL so a crashed turn can never wedge the chat.
import threading as _threading
import time as _time

_INFLIGHT_TURNS: Dict[Tuple[str, str], float] = {}
_INFLIGHT_LOCK = _threading.Lock()
_INFLIGHT_TTL_SECONDS: float = 300.0


def _inflight_key(chats_path: Any, text: str) -> Tuple[str, str]:
    """Key for the double-tap guard (never raises)."""
    try:
        return (str(chats_path or ""), " ".join(str(text or "").lower().split()))
    except Exception:
        return ("", "")


def _claim_inflight(key: Tuple[str, str]) -> bool:
    """Claim an in-flight turn; False when a live duplicate exists."""
    try:
        now = _time.time()
        with _INFLIGHT_LOCK:
            started = _INFLIGHT_TURNS.get(key)
            if started is not None and now - float(started) < _INFLIGHT_TTL_SECONDS:
                return False
            # Expired or absent: (re)claim. Prune opportunistically.
            try:
                expired = [k for k, v in _INFLIGHT_TURNS.items()
                           if now - float(v) >= _INFLIGHT_TTL_SECONDS]
                for k in expired:
                    _INFLIGHT_TURNS.pop(k, None)
            except Exception:
                logger.debug("inflight prune failed", exc_info=True)
            _INFLIGHT_TURNS[key] = now
            return True
    except Exception:
        logger.debug("inflight claim failed; allowing turn", exc_info=True)
        return True


def _release_inflight(key: Tuple[str, str]) -> None:
    """Release an in-flight turn claim (never raises)."""
    try:
        with _INFLIGHT_LOCK:
            _INFLIGHT_TURNS.pop(key, None)
    except Exception:
        logger.debug("inflight release failed", exc_info=True)


def _atomic_turn(store: Any, fn: Any) -> Any:
    """Execute a turn atomically under the chat file lock.

    Uses the store's _mutate_chats method which holds the per-file lock
    across the entire read-modify-write, preventing concurrent turns
    from losing each other's messages.
    """
    return store._mutate_chats(lambda data: fn(data))


def _sanitize_corrections(result: Any) -> List[List[str]]:
    """Typo corrections for the UI note (never raises, metadata only).

    Caps at 5 pairs of short strings from the agent result; anything
    malformed yields []. Persisted on the message so history renders
    the note without another model call.
    """
    try:
        raw = (result or {}).get("corrections") if isinstance(result, dict) else []
        clean: List[List[str]] = []
        for pair in (raw or []):
            try:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                orig, fixed = str(pair[0])[:32], str(pair[1])[:32]
                if orig and fixed and orig.lower() != fixed.lower():
                    clean.append([orig, fixed])
            except Exception:
                logger.debug("correction pair skipped", exc_info=True)
                continue
            if len(clean) >= 5:
                break
        return clean
    except Exception:
        logger.debug("corrections sanitize failed", exc_info=True)
        return []


def _complete_turn(ctx: UserContext, send_text: str,
                   prior_history: List[BaseMessage],
                   prior_raw: List[Dict[str, Any]],
                   image_ids: List[str], memory_notes: str,
                   project_context: str, deep_mode: bool,
                   force_search: bool,
                    active_tier: Optional[str],
                    on_token: Any = None,
                    on_reset: Any = None,
                    on_progress: Any = None,
                    cancel: Any = None) -> Tuple[Dict[str, Any], str, str, Optional[Dict[str, str]]]:
    """Run the agent and build the assistant message (no persistence)."""
    from agent.prompts import strip_internal_reasoning

    # Re-bind the user on this thread: stream workers, cascade executors
    # and pool threads do not inherit contextvars, and a lost binding
    # surfaces in tools as "no user context" (the exact failure in the
    # lecture_6.ppt screenshot). Re-binding here is idempotent and cheap.
    try:
        from backend.deps import bind_request_user as _bind

        _bind(ctx.user_id, ctx.limit_key or ctx.user_id, ctx.source or "")
    except Exception:
        logger.debug("turn thread re-bind failed", exc_info=True)

    try:
        before_ids = {m.id for m in ctx.file_store.list_outputs()}
    except Exception:
        before_ids = set()

    result = agent.answer_with_fallback(
        send_text,
        prior_history,
        first=(active_tier or None),
        memory_notes=memory_notes,
        raw_messages=prior_raw,
        deep_mode=bool(deep_mode),
        force_web_search=bool(force_search),
        image_upload_ids=image_ids,
        project_context=project_context,
        on_token=on_token,
        on_reset=on_reset,
        on_progress=on_progress,
        cancel=cancel,
    )
    output = strip_internal_reasoning(str(result.get("output", "")))
    tier = str(result.get("active_tier", "") or "")
    task_type = str(result.get("task_type", "") or "")
    tools_used = [t for t in (result.get("tools_used", []) or []) if isinstance(t, str)]
    sources = _clean_sources(result.get("sources", []) or [])

    try:
        fresh = [m for m in ctx.file_store.list_outputs() if m.id not in before_ids]
    except Exception:
        fresh = []
    new_artifacts = [
        {"id": m.id, "kind": m.kind,
         "name": str(m.display_name)[:MAX_DISPLAY_NAME_CHARS]}
        for m in fresh
    ]

    reported = result.get("fallback")
    agent_fallback = dict(reported) if isinstance(reported, dict) else None
    ui_fallback = _fallback_info(active_tier, tier) or agent_fallback
    assistant_msg: Dict[str, Any] = {
        "role": "assistant",
        "content": output,
        "time": utcnow_iso(),
        **_assistant_meta(tools_used, sources, force_search, deep_mode, tier,
                          ui_fallback),
    }
    corrections = _sanitize_corrections(result)
    if corrections:
        assistant_msg["corrections"] = corrections
    if new_artifacts:
        assistant_msg["artifacts"] = new_artifacts
    return assistant_msg, tier, task_type, ui_fallback


def _apply_attachment_gate(ctx: UserContext, gate_text: str,
                           history: List[Dict[str, Any]],
                           attachments: List[Dict[str, Any]],
                           image_ids: List[str], send_text: str,
                           active_tier: Optional[str]) -> Tuple[str, List[str], Optional[str]]:
    """Reuse history files for the gate, or ask for clarification.

    gate_text must be the RAW user text (never hint-augmented: attachment
    hints would confuse the classifier into different verdicts per path).
    history is the candidate pool (open conversation for sends, truncated
    prior for regenerates). Returns (send_text, vision_ids, clarify):
    clarify is None normally, else the question to persist instead of
    calling any model.
    """
    # CURRENT message decides ACTIVE context. History is AVAILABLE, never
    # auto-injected: the gate selects only explicitly/clearly referenced
    # files so one chat can mix image/doc/ppt/song/code turns safely.
    # ponytail: gate scans last 10 msgs; widen only if multi-file chats miss.
    vision_ids = list(image_ids)
    # Stateless teaching session: explicit request or short Next/continue
    # inside an active teaching thread bypasses the normal gate so "Next"
    # keeps the SAME file/window instead of restarting blind or mixing files.
    try:
        _teaching_hit = (
            _is_teaching_request(gate_text)
            or _is_teaching_continuation(gate_text, history)
            or _is_pace_feedback(gate_text, history)
        )
    except Exception:
        _teaching_hit = False
    if _teaching_hit:
        try:
            return _apply_teaching_session(
                ctx, gate_text, history, attachments, image_ids, send_text
            )
        except Exception:
            logger.debug("teaching session stage failed; falling back to gate", exc_info=True)
    needs_docs = not any(a.get("kind") in ("document", "pdf", "csv") for a in attachments)
    if not vision_ids or needs_docs:
        from agent.attachment_gate import decide as _gate_decide

        avail_images, avail_docs = _available_for_gate(ctx, history)
        decision = _gate_decide(gate_text, avail_images, avail_docs,
                                classifier=_attachment_classifier(active_tier))
        if decision.get("clarify") and not attachments:
            return send_text, vision_ids, str(decision["clarify"])
        if not vision_ids:
            vision_ids = [str(e.get("id")) for e in (decision.get("use_images") or [])
                          if isinstance(e, dict) and e.get("id")]
            if vision_ids:
                send_text += (
                    "\n\n[Note: the user refers to image(s) sent earlier in "
                    "this conversation; their content is provided alongside "
                    "this request when answered by a vision-capable model.]"
                )
        if needs_docs:
            reused = [dict(e) for e in (decision.get("use_docs") or [])
                      if isinstance(e, dict) and e.get("id")]
            if reused:
                total_r = len(reused)
                if total_r > 1:
                    send_text += attachments_overview(reused)
                for position, attach in enumerate(reused, start=1):
                    send_text += attachment_hint(
                        attach["kind"], attach["id"], attach["name"], position, total_r)
                for attach in reused:
                    send_text += _attachment_text_hint(ctx, attach)
                send_text += (
                    "\n\n[Note: the user refers to file(s) sent earlier in "
                    "this conversation; use the upload ID(s) above.]"
                )
    # Image-thread follow-up: disputes/drills ("I think ii) is c") carry
    # no nouns for the gate above, yet reference shared Q&A context from
    # a recent image. Reuse it so text tiers answer from the transcript
    # instead of asking for wording they could read themselves.
    if not vision_ids and not attachments:
        try:
            from agent.attachment_gate import is_image_followup as _followup
            follow_id = _followup(gate_text, history)
            if follow_id:
                vision_ids = [str(follow_id)]
                send_text += (
                    "\n\n[Note: the user refers to image(s) sent earlier in "
                    "this conversation; their content is provided alongside "
                    "this request when answered by a vision-capable model.]"
                )
        except Exception:
            logger.debug("image followup reuse failed", exc_info=True)
    return send_text, vision_ids, None


def run_chat(ctx: UserContext, content: str,
             upload_ids: Optional[List[str]] = None,
             project_id: Optional[str] = None,
             deep_mode: bool = False,
             force_search: bool = False,
             active_tier: Optional[str] = None,
             on_token: Any = None,
             on_reset: Any = None,
             on_progress: Any = None,
             cancel: Any = None) -> Dict[str, Any]:
    """Run one user turn end-to-end; returns send-response payload.

    Persists both messages before returning. Raises HTTPException for
    rate limits (429) and saturation (503), ValueError for bad
    input/attachments, RuntimeError (user-safe message) when every tier
    fails. on_token/on_reset stream live answer tokens (see
    agent.executor.TokenStream); on_progress streams per-tool-round
    status lines (tool names only). cancel is an optional zero-arg
    callable polled between tool rounds: a True return raises
    TurnCancelled, aborting without synthesis or persistence.
    """
    text = str(content or "").strip()
    if not text:
        raise ValueError("Message is empty.")
    store = ctx.user_store
    # Double-tap guard BEFORE rate limits: an identical message already
    # generating in this chat short-circuits without burning quota or
    # producing a duplicate answer. Regenerates are unaffected (the
    # prior turn has completed, so no claim is held).
    _dup_key = _inflight_key(getattr(store, "chats_path", ""), text)
    if not _claim_inflight(_dup_key):
        dupe_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": ("I'm still generating the answer to that message — "
                        "it will appear above when ready. No need to resend."),
            "time": utcnow_iso(),
            **_assistant_meta([], [], bool(force_search), bool(deep_mode),
                               "clarify", None),
        }
        _append_turn_atomic(store, {"role": "user", "content": text,
                                    "time": utcnow_iso()}, dupe_msg)
        return {
            "message": dupe_msg,
            "active_tier": "clarify",
            "task_type": "clarify",
            "warnings": [],
            "fallback": None,
            "corrections": [],
        }
    try:
        return _run_chat_inner(
            ctx, text, store, upload_ids, project_id, deep_mode,
            force_search, active_tier, on_token, on_reset, on_progress,
            cancel)
    finally:
        _release_inflight(_dup_key)


def _run_chat_inner(ctx: UserContext, text: str, store: Any,
                    upload_ids: Optional[List[str]] = None,
                    project_id: Optional[str] = None,
                    deep_mode: bool = False,
                    force_search: bool = False,
                    active_tier: Optional[str] = None,
                    on_token: Any = None,
                    on_reset: Any = None,
                    on_progress: Any = None,
                    cancel: Any = None) -> Dict[str, Any]:
    """Original run_chat body (in-flight claim held by the caller)."""
    _check_limits(ctx.limit_key or ctx.user_id, bool(deep_mode))

    # Snapshot state under a short lock hold — never hold the chats lock
    # across LLM/network I/O (that serialized all turns). Final append
    # uses _mutate_chats (read-modify-write under lock) so concurrent
    # turns don't lose each other's messages.
    with _chats_path_lock(store.chats_path):
        chats, current, warnings = _load_state(store)

    attachments, image_ids = _resolve_attachments(ctx, upload_ids or [])

    send_text = text
    total = len(attachments)
    if total > 1:
        send_text += attachments_overview(attachments)
    for position, attach in enumerate(attachments, start=1):
        send_text += attachment_hint(
            attach["kind"], attach["id"], attach["name"], position, total)
    for attach in attachments:
        send_text += _attachment_text_hint(ctx, attach)

    user_msg: Dict[str, Any] = {
        "role": "user",
        "content": text,
        "time": utcnow_iso(),
    }
    if attachments:
        user_msg["attachments"] = attachments
    if image_ids:
        user_msg["image"] = image_ids[0]
        if len(image_ids) > 1:
            user_msg["images"] = list(image_ids)

    prior_history = build_chat_history(
        [m for m in current if isinstance(m, dict)])
    prior_raw: List[Dict[str, Any]] = [
        dict(m) for m in current if isinstance(m, dict)]
    memory_notes, project_context = _memory_and_project(store, project_id)

    send_text, vision_ids, clarify = _apply_attachment_gate(
        ctx, text, current, attachments, image_ids, send_text, active_tier)
    if clarify is not None:
        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": clarify,
            "time": utcnow_iso(),
            **_assistant_meta([], [], bool(force_search), bool(deep_mode),
                               "clarify", None),
        }
        _append_turn_atomic(store, user_msg, assistant_msg)
        return {
            "message": assistant_msg,
            "active_tier": "clarify",
            "task_type": "clarify",
            "warnings": warnings,
            "fallback": None,
            "corrections": [],
        }

    try:
        assistant_msg, tier, task_type, fallback = _complete_turn_guarded(
            ctx, send_text, prior_history, prior_raw, vision_ids,
            memory_notes, project_context, bool(deep_mode),
            bool(force_search), active_tier, on_token, on_reset,
            on_progress, cancel)
    except TurnCancelled:
        # Client went away: nobody left to read a marker. Re-raise
        # untouched (never persisted, never cooled, never salvaged).
        raise
    except (BudgetExhausted, RuntimeError, HTTPException) as e:
        # Failed turns used to persist NOTHING — not even the user's
        # message — so any retry started cold and Model B redid (or
        # lost) Model A's work. Persist user + failed marker instead:
        # regenerating the marker retries in place with full history.
        # Rate-limit rejections happen before user_msg exists, so they
        # never reach here; validation errors (ValueError) are the
        # caller's to fix, not to retry.
        _append_turn_atomic(store, user_msg, _failed_turn_message(
            e, bool(force_search), bool(deep_mode)))
        raise

    try:
        fixed, repaired, left = _maybe_repair_teaching_turn(
            send_text, str(assistant_msg.get("content", "")), tier,
            on_token, on_reset)
        if repaired:
            assistant_msg = dict(assistant_msg)
            assistant_msg["content"] = fixed
        _log_teaching_format(send_text, str(assistant_msg.get("content", "")),
                             tier, repaired=repaired, violations=len(left))
    except Exception:
        try:
            _log_teaching_format(send_text, str(assistant_msg.get("content", "")), tier)
        except Exception:
            logger.debug("teaching format log failed", exc_info=True)
    persisted, live = _turn_approvals(ctx)
    if persisted:
        assistant_msg = dict(assistant_msg)
        assistant_msg["pending_approvals"] = persisted
    _append_turn_atomic(store, user_msg, assistant_msg)
    return {
        "message": assistant_msg,
        "active_tier": tier,
        "task_type": task_type,
        "warnings": warnings,
        "fallback": fallback,
        "pending_approvals": live,
        "corrections": list(assistant_msg.get("corrections", []) or []),
    }


def _failed_turn_reason(error: Any) -> str:
    """Short user-facing cause for a failed-turn marker (never raises)."""
    try:
        if isinstance(error, BudgetExhausted):
            return "the request hit its time/call limits partway"
        if isinstance(error, HTTPException):
            try:
                code = int(getattr(error, "status_code", 0) or 0)
            except Exception:
                code = 0
            if code == 503:
                return "the server was busy"
            if code == 429:
                return "a rate limit was hit"
            return "the server had trouble"
        return "all models were unavailable"
    except Exception:
        return "all models were unavailable"


def _failed_turn_message(error: Any, force_search: bool, deep_mode: bool) -> Dict[str, Any]:
    """Recoverable failed-turn marker (user request stays retryable)."""
    return {
        "role": "assistant",
        "content": (
            f"I couldn't complete that request ({_failed_turn_reason(error)}). "
            "Your message is saved — tap Regenerate to retry it in place, "
            "or send a follow-up to continue."),
        "time": utcnow_iso(),
        "failed": True,
        **_assistant_meta([], [], bool(force_search), bool(deep_mode), "", None),
    }


def _append_turn_atomic(store: Any, *msgs: Dict[str, Any]) -> None:
    """Append messages atomically (read-modify-write under lock)."""
    clean = [dict(m) for m in msgs if isinstance(m, dict)]

    def _fn(data: Any) -> Any:
        if not isinstance(data, dict):
            data = {}
        chats = data.get("chats", [])
        current = data.get("current", [])
        if not isinstance(chats, list):
            chats = []
        if not isinstance(current, list):
            current = []
        data["chats"] = chats
        data["current"] = list(current) + clean
        return data

    try:
        store._mutate_chats(_fn)
    except AttributeError:
        # Fallback for test doubles without _mutate_chats.
        chats, current, _w = _load_state(store)
        store.save_chats(chats, list(current) + clean)


def _replace_message_atomic(store: Any, index: int, msg: Dict[str, Any]) -> None:
    """Replace the message at index atomically (regenerate-in-place)."""
    clean = dict(msg) if isinstance(msg, dict) else {}

    def _is_failed_slot(msgs: Any) -> bool:
        try:
            return (isinstance(index, int) and isinstance(msgs, list)
                    and 0 <= index < len(msgs)
                    and isinstance(msgs[index], dict)
                    and msgs[index].get("role") == "assistant"
                    and msgs[index].get("failed") is True)
        except Exception:
            return False

    def _fn(data: Any) -> Any:
        if not isinstance(data, dict):
            data = {}
        current = data.get("current", [])
        if not isinstance(current, list):
            current = []
        if _is_failed_slot(current):
            updated = list(current)
            updated[index] = clean
            data["current"] = updated
        else:
            # Slot shifted or healed under us (concurrent turn): append
            # rather than overwrite a live answer or drop the fresh one.
            data["current"] = list(current) + ([clean] if clean else [])
        return data

    try:
        store._mutate_chats(_fn)
    except AttributeError:
        # Fallback for test doubles without _mutate_chats.
        chats, current, _w = _load_state(store)
        if _is_failed_slot(current):
            current = list(current)
            current[index] = clean
        else:
            current = list(current) + ([clean] if clean else [])
        store.save_chats(chats, current)


def _complete_turn_guarded(ctx: UserContext, send_text: str,
                           prior_history: List[BaseMessage],
                           prior_raw: List[Dict[str, Any]],
                           image_ids: List[str], memory_notes: str,
                           project_context: str, deep_mode: bool,
                           force_search: bool,
                           active_tier: Optional[str],
                           on_token: Any = None,
                           on_reset: Any = None,
                           on_progress: Any = None,
                           cancel: Any = None) -> Tuple[Dict[str, Any], str, str, Optional[Dict[str, str]]]:
    """_complete_turn with saturation mapped to HTTP 503 (fail fast)."""
    from fastapi import HTTPException

    try:
        return _complete_turn(
            ctx, send_text, prior_history, prior_raw, image_ids,
            memory_notes, project_context, deep_mode, force_search,
            active_tier, on_token, on_reset, on_progress, cancel)
    except ExecutorBusyError:
        raise HTTPException(
            status_code=503,
            detail="Server is busy, please retry in a moment.")


def regenerate_chat(ctx: UserContext, index: int,
                    project_id: Optional[str] = None,
                    deep_mode: bool = False,
                    force_search: bool = False,
                    active_tier: Optional[str] = None) -> Dict[str, Any]:
    """Append a fresh answer to an existing assistant message.

    Rebuilds the request from the stored preceding user message
    (content + attachment hints, same shape as a fresh send) with
    history ending before it. The original answer is kept — the new
    one is appended. Raises ValueError for bad indexes/shapes.
    """
    store = ctx.user_store
    _check_limits(ctx.limit_key or ctx.user_id, bool(deep_mode))

    # Serialize turns per user to prevent lost updates on concurrent regenerates.
    with _chats_path_lock(store.chats_path):
        chats, current, warnings = _load_state(store)
        msgs = [m for m in current if isinstance(m, dict)]
    if not isinstance(index, int) or not (0 <= index < len(msgs)):
        raise ValueError("Response to regenerate was not found.")
    assistant_msg = msgs[index]
    if assistant_msg.get("role") != "assistant":
        raise ValueError("Only assistant responses can be regenerated.")
    user_msg = None
    for pos in range(index - 1, -1, -1):
        if msgs[pos].get("role") == "user":
            user_msg = msgs[pos]
            user_index = pos
            break
    if user_msg is None:
        raise ValueError("Original request could not be recovered.")

    attachments = [
        a for a in (user_msg.get("attachments") or [])
        if isinstance(a, dict) and a.get("id")
    ]
    image_ids = [str(a["id"]) for a in attachments
                 if a.get("kind") == "image"]
    send_text = str(user_msg.get("content", "") or "")
    total = len(attachments)
    if total > 1:
        send_text += attachments_overview(attachments)
    for position, attach in enumerate(attachments, start=1):
        send_text += attachment_hint(
            str(attach.get("kind", "image")), str(attach.get("id", "")),
            str(attach.get("name", "file")), position, total)
    for attach in attachments:
        send_text += _attachment_text_hint(ctx, attach)

    prior = msgs[:user_index]
    prior_history = build_chat_history(prior)
    prior_raw = [dict(m) for m in prior]
    memory_notes, project_context = _memory_and_project(store, project_id)

    send_text, vision_ids, clarify = _apply_attachment_gate(
        ctx, str(user_msg.get("content", "") or ""), prior,
        [dict(a) for a in attachments], image_ids, send_text, active_tier)
    if clarify is not None:
        fresh_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": clarify,
            "time": utcnow_iso(),
            **_assistant_meta([], [], bool(force_search), bool(deep_mode),
                               "clarify", None),
        }
        _append_turn_atomic(store, fresh_msg)
        return {
            "message": fresh_msg,
            "active_tier": "clarify",
            "task_type": "clarify",
            "warnings": warnings,
            "fallback": None,
            "corrections": [],
        }

    fresh_msg, tier, task_type, fallback = _complete_turn_guarded(
        ctx, send_text, prior_history, prior_raw, vision_ids,
        memory_notes, project_context, bool(deep_mode),
        bool(force_search), active_tier)

    try:
        fixed, repaired, left = _maybe_repair_teaching_turn(
            send_text, str(fresh_msg.get("content", "")), tier)
        if repaired:
            fresh_msg = dict(fresh_msg)
            fresh_msg["content"] = fixed
        _log_teaching_format(send_text, str(fresh_msg.get("content", "")),
                             tier, repaired=repaired, violations=len(left))
    except Exception:
        try:
            _log_teaching_format(send_text, str(fresh_msg.get("content", "")), tier)
        except Exception:
            logger.debug("regen teaching format log failed", exc_info=True)
    persisted, live = _turn_approvals(ctx)
    if persisted:
        fresh_msg = dict(fresh_msg)
        fresh_msg["pending_approvals"] = persisted
    if isinstance(assistant_msg, dict) and assistant_msg.get("failed") is True:
        # Regenerating a failed marker retries it IN PLACE (replace,
        # never append): otherwise the dead marker and the fresh answer
        # render as phantom "versions" of each other.
        _replace_message_atomic(store, index, fresh_msg)
    else:
        _append_turn_atomic(store, fresh_msg)
    return {
        "message": fresh_msg,
        "active_tier": tier,
        "task_type": task_type,
        "warnings": warnings,
        "fallback": fallback,
        "pending_approvals": live,
        "corrections": list(fresh_msg.get("corrections", []) or []),
    }


EPISODIC_MIN_MESSAGES: int = 12


EPISODIC_SUMMARY_CHARS: int = 2000


def maybe_attach_episodic_summary(record: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a rolling summary to an archived chat (best-effort, never raises).

    Only chats with at least EPISODIC_MIN_MESSAGES get one, generated on a
    cheap tier (never the answer tiers). Failures leave the record
    untouched — archiving must never break. The summary surfaces in
    recents payloads; model-context injection on reopen is deferred.
    """
    try:
        if not isinstance(record, dict) or record.get("summary"):
            return record
        msgs = record.get("messages", [])
        if not isinstance(msgs, list) or len(msgs) < EPISODIC_MIN_MESSAGES:
            return record
        lines = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            role = "User" if m.get("role") == "user" else "AI"
            lines.append(f"{role}: {str(m.get('content', ''))[:200]}")
        if not lines:
            return record
        from agent.cascade import _run_cascade_step
        from agent.prompts import _as_text
        from config import CHEAP_TIERS

        prompt = ("Summarize this conversation for future context in at most "
                  "5 lines: key topics, decisions, and user preferences.\n\n"
                  + "\n".join(lines))
        _, summary = _run_cascade_step(
            lambda _n, llm: _as_text(agent._invoke_bounded(
                llm, [HumanMessage(content=prompt)], timeout=30.0).content),
            None, CHEAP_TIERS)
        summary = str(summary or "").strip()[:EPISODIC_SUMMARY_CHARS]
        if summary:
            record["summary"] = summary
        return record
    except Exception:
        return record


def archive_current(current: List[Dict[str, Any]],
                    project_id: Optional[str] = None,
                    chat_id: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Split the open conversation into a history record (pure logic).

    Returns (record, empty_current). Raises ValueError when empty.
    The caller owns the open conversation's id (like a client-side
    current-chat id): pass it back to keep identity stable
    across open/archive cycles, else a fresh id is minted.
    """
    msgs = [dict(m) for m in current if isinstance(m, dict)]
    if not msgs:
        raise ValueError("Nothing to archive.")
    title = next(
        (str(m.get("content", "")) for m in msgs if m.get("role") == "user"),
        "Untitled",
    )
    record: Dict[str, Any] = {
        "id": str(chat_id) if is_valid_id(chat_id) else new_conversation_id(),
        "title": title.strip()[:MAX_CHAT_TITLE_CHARS] or "Untitled",
        "messages": msgs,
        # ponytail: single choke point — every archive (new/edited) gets fresh time
        "updated_at": utcnow_iso(),
    }
    if is_valid_id(project_id):
        record["project_id"] = str(project_id)
    return record, []
