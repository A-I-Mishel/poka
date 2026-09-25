"""Teaching stage: single-file window selection for lecture sessions.

Moved verbatim from backend.flow (_apply_teaching_session only).
"""

from typing import (Any, Dict, List, Optional, Tuple)
import logging
from backend.deps import UserContext

from backend.attachments import (_escape_hint, attachment_hint, attachments_overview)
from backend.flow.stages import _available_for_gate
from backend.teach import (TEACHING_SUFFIX, TEACHING_WINDOW_SLIDES, _extract_teaching_blocks, _is_admin_block, _is_recall_answer, _is_teaching_request, _last_teaching_state, _pace_direction, _teaching_scope_line, _teaching_window_hint, _time_pressure)

logger = logging.getLogger(__name__)


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
        from backend.teach import _has_teaching_header_in_recent, _teaching_flag_in_recent
        _flag = _teaching_flag_in_recent(history, window=10)
        _prior_session = _flag is not None or _has_teaching_header_in_recent(history, window=10)
    except Exception:
        try:
            _prior_session = any(
                isinstance(m, dict) and "📘 file:" in str(m.get("content", "") or "").lower()
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
            logger.debug("teaching candidate build failed; skipping entry", exc_info=True)
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
        logger.debug("teaching file pick failed; keeping first candidate", exc_info=True)
    # Cursor: end slide of the active file's last taught window.
    _, last_end = _last_teaching_state(history)
    # Explicit reteach ("teach X again", "restart") restarts at 1 —
    # otherwise a past-end cursor yields an empty window (no wrap).
    try:
        if _explicit_file:
            low2 = str(gate_text or "").lower()
            if any(k in low2 for k in ("again", "restart", "from start", "from the start", "from scratch")):
                last_end = 0
    except Exception:
        logger.debug("reteach cursor reset failed", exc_info=True)
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
        logger.debug("teaching cursor file-switch check failed", exc_info=True)
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
        logger.debug("teaching exhaustion probe failed", exc_info=True)
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
                    logger.debug("exam counts probe failed", exc_info=True)
                    _exam_counts.append(f"'{_escape_hint(str(c.get('name','file')))}'")
            send_text += attachments_overview(candidates)
            for position, attach in enumerate(candidates, start=1):
                try:
                    send_text += attachment_hint(
                        attach["kind"], attach["id"], attach["name"], position, len(candidates))
                except Exception:
                    logger.debug("exam hint attach failed", exc_info=True)
            # Grounding for citation demands: the exam packet must cite
            # [slide N], but no fresh window exists past the end (single-
            # block legacy dumps always land here on "next"). Re-attach a
            # compact tail of the final file's source text so citations
            # resolve to verified content instead of memory. Bounded,
            # source-only, never model output. (Not a "Verified content"
            # window: no new teaching happens on this turn.)
            try:
                _tail_blocks, _, _tail_status = _extract_teaching_blocks(
                    ctx, active)
            except Exception:
                logger.debug("exam grounding extract failed", exc_info=True)
                _tail_blocks, _tail_status = [], "FAILED"
            if _tail_status == "OK" and _tail_blocks:
                try:
                    _tail = _tail_blocks[-TEACHING_WINDOW_SLIDES:]
                    _ref_parts = []
                    _ref_chars = 0
                    for _num, _body in _tail:
                        _piece = f"[slide {_num}]\n{str(_body or '').strip()}"
                        if _ref_chars + len(_piece) > 2000 and _ref_parts:
                            break
                        _ref_parts.append(_piece)
                        _ref_chars += len(_piece)
                    if _ref_parts:
                        send_text += (
                            "\n\n[Reference for citation grounding (last taught "
                            "content, source text — not new material):\n"
                            + "\n".join(_ref_parts).strip() + "]"
                        )
                except Exception:
                    logger.debug("exam grounding render failed", exc_info=True)
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
        logger.debug("exam mode assembly failed", exc_info=True)
    # Window first: the pointer below is fetch-neutral only on clean
    # windows (verified text inline — must not command a re-fetch).
    # Thin/truncated/overflow windows keep the classic fetch pointer so
    # the model can still reach diagram/overflow pages.
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
            logger.debug("readable-candidate advance failed", exc_info=True)
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
    # Single-file hint (no multi-file overview: never mix files in one
    # batch). Fetch-neutral only on clean windows — the same predicate as
    # the no-refetch note below and agent.toolrun's unbind/drop guards
    # (keep the three in sync). Thin/truncated/overflow windows keep the
    # classic fetch pointer so diagrams stay reachable.
    try:
        _teaching_clean = (
            status == "OK"
            and TEACHING_INLINE_OVERFLOW not in window_hint
            and "title-only" not in window_hint
            and "truncated to fit context" not in window_hint
        )
        send_text += attachment_hint(active["kind"], active["id"], active["name"], 1, 1,
                                     teaching=_teaching_clean)
    except Exception:
        logger.debug("single-file hint attach failed", exc_info=True)
    send_text += window_hint
    # No-refetch note: when the verified window is complete inline (OK
    # status, full-bodied, untruncated), teach from the text above instead
    # of re-fetching the whole file. The read pointer stays for
    # diagram/overflow pages named by other notes; overflow, thin
    # (title-only), and truncated windows keep the fetch behavior.
    try:
        if (status == "OK"
                and TEACHING_INLINE_OVERFLOW not in window_hint
                and "title-only" not in window_hint
                and "truncated to fit context" not in window_hint):
            send_text += (
                "\n\n[Teach ONLY from the verified window text above; do not "
                "re-fetch the file and ignore the read pointer above unless "
                "a later note names diagram/overflow pages.]"
            )
    except Exception:
        logger.debug("teaching no-refetch note failed", exc_info=True)
    # Last window of a file: close with a compact section review.
    try:
        if status == "OK" and total and end >= total:
            send_text += (
                f"\n\n[This is the last window of '{_escape_hint(str(active.get('name','file')))}'. "
                "After teaching it, end with a compact section review: key definitions, "
                "formulas, distinctions, common traps, plus one recall question.]"
            )
    except Exception:
        logger.debug("last-window review note failed", exc_info=True)
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
                    logger.debug("analysis counts probe failed", exc_info=True)
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
                    logger.debug("admin compression note failed", exc_info=True)
    except Exception:
        logger.debug("teaching analysis header failed", exc_info=True)
    send_text += TEACHING_SUFFIX
    # Dynamic scope fence: name the exact allowed slides for this turn.
    try:
        if status == "OK" and start and end:
            send_text += _teaching_scope_line(start, end, total)
    except Exception:
        logger.debug("teaching scope fence failed", exc_info=True)
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
        logger.debug("recall-answer note failed", exc_info=True)
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
        logger.debug("pace feedback note failed", exc_info=True)
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
        logger.debug("time-pressure note failed", exc_info=True)
    send_text += (
        "\n\n[Note: the user is in a teaching session for the file above; "
        "use its upload ID and verified window only.]"
    )
    return send_text, vision_ids, None
