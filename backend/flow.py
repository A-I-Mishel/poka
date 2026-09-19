"""Chat turn orchestration: send/regenerate entry points.

History building, rate limits, gate + teaching application, agent
invocation, provenance, persistence. Implements run_chat /
regenerate_chat (used by backend.routers.chat) and archive helpers
(used by backend.routers.chats); teaching and attachment primitives
come from backend.teach and backend.attachments.
"""

from typing import (Any, Dict, List, Optional, Tuple)
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
import agent
from agent.executor import ExecutorBusyError
from services.limits import MAX_CHAT_TITLE_CHARS, MAX_DISPLAY_NAME_CHARS
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter
from services.storage import (StorageError, clean_source_record, is_valid_id, new_conversation_id)
from services.timeutil import utcnow_iso
from backend.deps import UserContext

from backend.attachments import (_attachment_text_hint, _escape_hint, _recent_document_attachments, _recent_image_ids, _resolve_attachments, attachment_hint, attachments_overview)
from backend.teach import (TEACHING_SUFFIX, _extract_teaching_blocks, _is_admin_block, _is_pace_feedback, _is_recall_answer, _is_teaching_continuation, _is_teaching_request, _last_teaching_state, _log_teaching_format, _maybe_repair_teaching_turn, _pace_direction, _teaching_scope_line, _teaching_window_hint, _time_pressure)

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
        pass

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
    if new_artifacts:
        assistant_msg["artifacts"] = new_artifacts
    return assistant_msg, tier, task_type, ui_fallback


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


def _apply_teaching_session(
    ctx: UserContext,
    gate_text: str,
    history: List[Dict[str, Any]],
    attachments: List[Dict[str, Any]],
    image_ids: List[str],
    send_text: str,
) -> Tuple[str, List[str], Optional[str]]:
    """Teaching path: ONE active file + current 3-slide window (never raises).

    Stateless: candidates are current attachments + AVAILABLE history docs
    (deduped, sorted by name); the cursor comes from the last "📘 FILE:"
    header. Never mixes files in one batch. Fail-closed HARD: when an active
    session has no verified window, return a server message with NO model
    call (clarify short-circuit) so a disobedient tier cannot hallucinate
    slides. Only a fresh explicit request with no files at all falls through
    to the model (general-knowledge teaching, no source claims allowed).
    """
    TEACHING_INLINE_OVERFLOW = "exceeds the inline window"
    try:
        _explicit_request = _is_teaching_request(gate_text)
    except Exception:
        _explicit_request = False
    try:
        _prior_session = any(
            isinstance(m, dict) and "📘 FILE:" in str(m.get("content", "") or "")
            for m in (history or [])[-10:]
        )
    except Exception:
        _prior_session = False
    vision_ids = list(image_ids or [])
    try:
        _, avail_docs = _available_for_gate(ctx, history)
    except Exception:
        avail_docs = []
    # Candidates: current teachable uploads + history docs (dedupe, sort).
    seen: set = set()
    candidates: List[Dict[str, str]] = []
    for src in (attachments or []) + (avail_docs or []):
        try:
            if not isinstance(src, dict):
                continue
            if str(src.get("kind", "")) not in ("document", "pdf"):
                continue
            uid = str(src.get("id", "") or "")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            candidates.append({
                "id": uid,
                "kind": str(src.get("kind", "document")),
                "name": str(src.get("name", "file") or "file"),
            })
        except Exception:
            continue
    candidates.sort(key=lambda e: str(e.get("name", "")).lower())
    if not candidates:
        if _explicit_request and not _prior_session:
            # Fresh ask with no files: general-knowledge teaching is allowed,
            # so let the model answer (it must not claim source slides).
            send_text += (
                "\n\n[Teaching requested but no readable slides were found in "
                "this conversation. Ask the user to upload the .pptx/.pdf lecture "
                "files first. Do not invent slides.]"
            )
            return send_text, vision_ids, None
        # Active session lost its files (pruned/deleted): no model call.
        return send_text, vision_ids, (
            "The files from this teaching session are no longer available "
            "(deleted or expired), so I stopped rather than guess their contents. "
            "Please re-upload the lecture slides and say Next to continue."
        )
    # Pick ONE active file: explicit filename > continuation file > first.
    active = candidates[0]
    _explicit_file = False
    try:
        low = str(gate_text or "").lower()
        # Explicit filename wins (same stem rule as the gate).
        named = None
        for c in candidates:
            nm = str(c.get("name", "") or "").lower()
            stem = nm.rsplit(".", 1)[0] if "." in nm else nm
            if (len(nm) >= 4 and nm in low) or (len(stem) >= 4 and stem in low):
                named = c
                break
        if named is not None:
            active = named
            _explicit_file = True
        else:
            lname, _ = _last_teaching_state(history)
            if lname:
                for c in candidates:
                    if str(c.get("name", "")).strip().lower() == lname.strip().lower():
                        active = c
                        break
                else:
                    # Fuzzy: last teaching basename matches a candidate stem.
                    lbase = lname.rsplit(".", 1)[0].strip().lower() if "." in lname else lname.strip().lower()
                    for c in candidates:
                        nm = str(c.get("name", "") or "")
                        stem = (nm.rsplit(".", 1)[0] if "." in nm else nm).strip().lower()
                        if lbase and (lbase == stem or lbase in stem or stem in lbase):
                            active = c
                            break
    except Exception:
        pass
    # Cursor: end slide of the active file's last taught window.
    _, last_end = _last_teaching_state(history)
    # If the last header was for a DIFFERENT file, restart at 1.
    try:
        last_name, _ = _last_teaching_state(history)
        if last_name and last_name.strip().lower() != str(active.get("name", "")).strip().lower():
            # Check fuzzy mismatch too: different stems mean a file switch.
            a = str(active.get("name", "") or "")
            a_stem = (a.rsplit(".", 1)[0] if "." in a else a).strip().lower()
            l_stem = (last_name.rsplit(".", 1)[0] if "." in last_name else last_name).strip().lower()
            if a_stem != l_stem:
                last_end = 0
    except Exception:
        pass
    # If the active file is exhausted, advance to the next sorted file.
    # If every file is covered, switch to EXAM MODE instead of restarting.
    try:
        _blocks_probe, _total_probe, _status_probe = _extract_teaching_blocks(ctx, active)
        if _status_probe == "OK" and _total_probe and last_end >= _total_probe:
            idx = next((i for i, c in enumerate(candidates) if c.get("id") == active.get("id")), 0)
            if idx + 1 < len(candidates):
                active = candidates[idx + 1]
                last_end = 0
    except Exception:
        pass
    # All material covered → EXAM MODE (rapid recall + practice, no restart).
    try:
        _is_last = next(
            (i for i, c in enumerate(candidates) if c.get("id") == active.get("id")),
            len(candidates) - 1,
        ) >= len(candidates) - 1
        if (not _explicit_file and _status_probe == "OK" and _total_probe
                and last_end >= _total_probe and _is_last):
            _exam_counts = []
            for c in candidates:
                try:
                    _, t, s = _extract_teaching_blocks(ctx, c)
                    _exam_counts.append(
                        f"'{_escape_hint(str(c.get('name','file')))}' ({t} slides)"
                        if s == "OK" else f"'{_escape_hint(str(c.get('name','file')))}'")
                except Exception:
                    _exam_counts.append(f"'{_escape_hint(str(c.get('name','file')))}'")
            send_text += attachments_overview(candidates)
            for position, attach in enumerate(candidates, start=1):
                try:
                    send_text += attachment_hint(
                        attach["kind"], attach["id"], attach["name"], position, len(candidates))
                except Exception:
                    pass
            send_text += (
                "\n\n[EXAM MODE: all verified material is covered (" + "; ".join(_exam_counts) +
                "). Do not reteach from the top. Give: 1) rapid recall questions on key "
                "concepts, 2) must-remember formulas/definitions, 3) a compact comparison "
                "of commonly confused concepts, 4) common traps, 5) 2-3 practice problems "
                "with step-by-step solutions, 6) final condensed revision plus likely weak "
                "areas to review. Cite sources as [slide N].]"
            )
            return send_text, vision_ids, None
    except Exception:
        pass
    # Single-file hint (no multi-file overview: never mix files in one batch).
    try:
        send_text += attachment_hint(active["kind"], active["id"], active["name"], 1, 1)
    except Exception:
        pass
    window_hint, start, end, total, status = _teaching_window_hint(ctx, active, last_end)
    if (status != "OK" and TEACHING_INLINE_OVERFLOW not in window_hint
            and last_end <= 0 and not _explicit_file):
        # Fresh auto-pick landed on an unreadable file: advance to the next
        # readable candidate instead of failing the whole turn.
        try:
            _idx0 = next((i for i, c in enumerate(candidates)
                          if c.get("id") == active.get("id")), 0)
            for _cand in candidates[_idx0 + 1:]:
                _wh, _st, _en, _to, _ss = _teaching_window_hint(ctx, _cand, 0)
                if _ss == "OK":
                    active = _cand
                    window_hint, start, end, total, status = _wh, _st, _en, _to, _ss
                    break
        except Exception:
            pass
    if status != "OK" and TEACHING_INLINE_OVERFLOW not in window_hint:
        # No verified window and the model cannot fetch it inline either
        # (overflow files keep the model path: read_document handles 200MB).
        # Anything else → server message, NO model call, so slides cannot
        # be invented from memory.
        _reason = status if status.startswith("STATUS=") else "unreadable file"
        return send_text, vision_ids, (
            f"I couldn't read '{str(active.get('name', 'file'))}' ({_reason}), "
            "so I stopped rather than guess its slides. Please re-upload an "
            "accessible .pptx/.pdf (export scanned slides with OCR text first), "
            "then say Next to continue."
        )
    send_text += window_hint
    # Last window of a file: close with a compact section review.
    try:
        if status == "OK" and total and end >= total:
            send_text += (
                f"\n\n[This is the last window of '{_escape_hint(str(active.get('name','file')))}'. "
                "After teaching it, end with a compact section review: key definitions, "
                "formulas, distinctions, common traps, plus one recall question.]"
            )
    except Exception:
        pass
    # Analysis header for the first turn of a file (content map: counts +
    # admin compression). Runs once per fresh file; later turns skip it.
    try:
        _, cur_end = _last_teaching_state(history)
        is_fresh_file = (cur_end <= 0) or (start <= 1)
        if is_fresh_file and status == "OK":
            counts = []
            for c in candidates:
                try:
                    blks, t, s = _extract_teaching_blocks(ctx, c)
                    if s != "OK":
                        counts.append(f"'{_escape_hint(str(c.get('name','file')))}' (unreadable)")
                        continue
                    n_admin = sum(1 for _, b in blks if _is_admin_block(b))
                    if n_admin:
                        counts.append(
                            f"'{_escape_hint(str(c.get('name','file')))}' ({t} slides, "
                            f"~{n_admin} admin summarized)"
                        )
                    else:
                        counts.append(f"'{_escape_hint(str(c.get('name','file')))}' ({t} slides)")
                except Exception:
                    counts.append(f"'{_escape_hint(str(c.get('name','file')))}'")
            if len(counts) > 1:
                send_text += (
                    "\n\n[Teaching analysis: " + "; ".join(counts) +
                    f". Teaching '{_escape_hint(str(active.get('name','file')))}' first, "
                    "in file order, one concept per turn. Admin slides are "
                    "summarized, not taught as full blocks.]"
                )
            elif counts:
                # Single file: still note admin compression when present.
                try:
                    ablks, _, astatus = _extract_teaching_blocks(ctx, active)
                    if astatus == "OK":
                        n_admin = sum(1 for _, b in ablks if _is_admin_block(b))
                        if n_admin:
                            send_text += (
                                f"\n\n[Teaching analysis: '{_escape_hint(str(active.get('name','file')))}' "
                                f"has ~{n_admin} admin slide(s) summarized; teaching "
                                "concepts only.]"
                            )
                except Exception:
                    pass
    except Exception:
        pass
    send_text += TEACHING_SUFFIX
    # Dynamic scope fence: name the exact allowed slides for this turn.
    try:
        if status == "OK" and start and end:
            send_text += _teaching_scope_line(start, end, total)
    except Exception:
        pass
    # Recall-answer mode: evaluate the student's answer before the next window.
    try:
        from agent.attachment_gate import CONTINUATION_SIGNALS
        from agent.router import _signals as _gate_signals

        _is_next = _gate_signals(str(gate_text or "").lower(), CONTINUATION_SIGNALS)
    except Exception:
        _is_next = False
    try:
        if not _is_next and _is_recall_answer(str(gate_text or ""), history):
            send_text += (
                "\n\n[The user just answered your Recall checkpoint above. First "
                "evaluate in 3-5 lines: if correct confirm the key idea and "
                "optionally refine wording; if partial name the missing piece; "
                "if incorrect name the misconception, explain why simply, and "
                "re-check briefly. Never mark an answer wrong without repairing "
                "the misconception. Only then teach the next window below.]"
            )
    except Exception:
        pass
    # Pace feedback: adapt speed/depth for the next window.
    try:
        _pace = _pace_direction(str(gate_text or ""))
        if _pace == "slow":
            send_text += (
                "\n\n[The learner asks to slow down: simplify, teach any missing "
                "prerequisite first, use smaller examples, explain the WHY. "
                "Do not advance faster than one small concept.]"
            )
        elif _pace == "fast":
            send_text += (
                "\n\n[The learner is comfortable: move faster, reduce repetition, "
                "raise difficulty with exam-level problems.]"
            )
    except Exception:
        pass
    # Time/depth pressure stated by the learner (exam soon vs mastery).
    try:
        _pressure = _time_pressure(str(gate_text or ""))
        if _pressure == "rush":
            send_text += (
                "\n\n[Time pressure: the exam is soon. Teach essentials and "
                "HIGH VALUE concepts only, keep blocks tight, rapid pace with "
                "compact recall. Skip LOW details.]"
            )
        elif _pressure == "deep":
            send_text += (
                "\n\n[Depth requested: full mechanism, extra worked examples, "
                "slower pace. Do not skip prerequisites.]"
            )
    except Exception:
        pass
    send_text += (
        "\n\n[Note: the user is in a teaching session for the file above; "
        "use its upload ID and verified window only.]"
    )
    return send_text, vision_ids, None


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
            pass
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
    _check_limits(ctx.limit_key or ctx.user_id, bool(deep_mode))
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
        current = current + [user_msg, assistant_msg]
        store.save_chats(chats, current)
        return {
            "message": assistant_msg,
            "active_tier": "clarify",
            "task_type": "clarify",
            "warnings": warnings,
            "fallback": None,
        }

    assistant_msg, tier, task_type, fallback = _complete_turn_guarded(
        ctx, send_text, prior_history, prior_raw, vision_ids,
        memory_notes, project_context, bool(deep_mode),
        bool(force_search), active_tier, on_token, on_reset,
        on_progress, cancel)

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
            pass
    persisted, live = _turn_approvals(ctx)
    if persisted:
        assistant_msg = dict(assistant_msg)
        assistant_msg["pending_approvals"] = persisted
    current = current + [user_msg, assistant_msg]
    store.save_chats(chats, current)
    return {
        "message": assistant_msg,
        "active_tier": tier,
        "task_type": task_type,
        "warnings": warnings,
        "fallback": fallback,
        "pending_approvals": live,
    }


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
        current = current + [fresh_msg]
        store.save_chats(chats, current)
        return {
            "message": fresh_msg,
            "active_tier": "clarify",
            "task_type": "clarify",
            "warnings": warnings,
            "fallback": None,
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
            pass
    persisted, live = _turn_approvals(ctx)
    if persisted:
        fresh_msg = dict(fresh_msg)
        fresh_msg["pending_approvals"] = persisted
    current = current + [fresh_msg]
    store.save_chats(chats, current)
    return {
        "message": fresh_msg,
        "active_tier": tier,
        "task_type": task_type,
        "warnings": warnings,
        "fallback": fallback,
        "pending_approvals": live,
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
