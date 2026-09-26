"""Experience ledger: Pluto-owned learning from task episodes.

Memory remembers what happened; this module learns from it. Each turn
records a tiny episode (task type, tool-name sequence, outcome, cost —
never prompts, keys, or user data). Repeated episodes are mined into
candidate lessons; only patterns with enough consistent evidence become
trusted; trusted lessons bias future tool choice for similar tasks.

Design constraints (the trust model):
- Tool names come from the TOOL_MAP allowlist ONLY (validated on
  record AND on load): a lesson can never smuggle unknown tools,
  prompts, or instructions. Lessons reorder tools; they never add,
  remove, or execute anything.
- Evidence is quality-weighted, not just counted: a clean first-try
  success counts fully; an answer that needed reflection polish or a
  format repair counts half (the tools may be fine — the turn was not
  clean); user rejection and failures count against. Ambiguous
  evidence never creates trust on its own.
- One unusual event changes nothing: trust needs MIN_SUPPORT
  supporting episodes with a 2:1 margin over contradictions.
- Episodes older than the TTL stop counting (providers and quotas
  drift; lessons must not fossilize).
- Lessons are per-user (no cross-user leakage), listed via the audit
  endpoint, and can be disabled/deleted. Disabled stays disabled.
- Model/provider agnostic by construction: episodes and lessons never
  record model names, prompts, or keys — only task shapes and tool
  names, which every tier shares.
- Every function never raises into callers: learning must never break
  answering.
"""

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EXPERIENCE_FILE = "experience.jsonl"
LESSONS_FILE = "experience.json"
EXPERIENCE_MAX_EPISODES: int = 500
EXPERIENCE_TTL_SECONDS: float = 30 * 24 * 3600.0
MINE_EVERY_EPISODES: int = 5
LESSON_MIN_SUPPORT: int = 3
LESSON_MARGIN_RATIO: float = 2.0
LESSON_MAX_SEQUENCE: int = 8

TASK_TYPES = frozenset({"simple", "research", "creative", "data", "multi_step", "vision"})
OUTCOMES = frozenset({"ok", "degraded", "failed"})
# Evidence quality per episode. clean: first-try success, full weight.
# polished: the turn completed but needed reflection rewrite or format
# repair — the tools may be fine, so it counts half, never full.
# disputed: the user later rejected this strategy (regenerate against
# it) — counts against, like a failure. Unknown values behave as clean
# (backward compatible with pre-quality rows).
QUALITIES = frozenset({"clean", "polished", "disputed"})
QUALITY_WEIGHT = {"clean": 1.0, "polished": 0.5, "disputed": 0.0}


def _user_dir(user_id: str):
    try:
        from services.storage import user_dir

        return user_dir(str(user_id or ""), create=False)
    except Exception:
        return None


def _tmp_for(path, stem: str):
    """Unique tmp sibling so concurrent writers never share one file."""
    try:
        token = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}"
    except Exception:
        token = str(os.getpid())
    return path.with_name(f"{stem}.tmp.{token}")


def _cap_value(v: Any, limit: int = 500) -> Any:
    """Bound stored signal/cost values; non-strings pass through."""
    try:
        if isinstance(v, str) and len(v) > limit:
            return v[:limit]
    except Exception:
        logger.debug("experience cap failed", exc_info=True)
    return v


def _valid_tool(name: Any) -> bool:
    """True when name is a known tool (allowlist; never raises)."""
    try:
        from agent.toolrun import TOOL_MAP

        return isinstance(name, str) and bool(name) and name in TOOL_MAP
    except Exception:
        return False


def _clean_sequence(tools: Any) -> List[str]:
    """Tool-name sequence with unknowns dropped (never raises)."""
    try:
        seq = [str(t) for t in (tools or []) if _valid_tool(t)]
        return seq[:LESSON_MAX_SEQUENCE]
    except Exception:
        return []


def _read_episodes(user_id: str) -> List[Dict[str, Any]]:
    """All stored episodes, oldest first (never raises)."""
    try:
        root = _user_dir(str(user_id or ""))
        if root is None:
            return []
        path = root / EXPERIENCE_FILE
        if not path.is_file():
            return []
        episodes: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except Exception:
                    logger.debug('experience line parse failed', exc_info=True)
                    continue
                if isinstance(entry, dict):
                    episodes.append(entry)
        return episodes
    except Exception:
        return []


def _prune_episodes(user_id: str) -> None:
    """Drop oldest episodes past the cap (never raises)."""
    try:
        root = _user_dir(str(user_id or ""))
        if root is None:
            return
        path = root / EXPERIENCE_FILE
        if not path.is_file():
            return
        try:
            from services.storage import path_lock as _plock
        except Exception:
            _plock = None
        if _plock is None:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) <= EXPERIENCE_MAX_EPISODES:
                return
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-EXPERIENCE_MAX_EPISODES:])
            return
        with _plock(path):
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) <= EXPERIENCE_MAX_EPISODES:
                return
            tmp = _tmp_for(path, EXPERIENCE_FILE)
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.writelines(lines[-EXPERIENCE_MAX_EPISODES:])
                os.replace(tmp, path)
            except Exception:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    logger.debug("experience prune tmp cleanup failed", exc_info=True)
                raise
    except Exception:
        logger.debug("experience prune failed", exc_info=True)


def record_episode(user_id: str, task_type: str, tools: Any, outcome: str,
                   signals: Optional[Dict[str, Any]] = None,
                   cost: Optional[Dict[str, Any]] = None,
                   tier: str = "", quality: str = "clean") -> bool:
    """Append one task episode; mine when due. Returns mined-now (never raises)."""
    try:
        user = str(user_id or "").strip()
        task = str(task_type or "").strip().lower()
        result = str(outcome or "").strip().lower()
        qual = str(quality or "").strip().lower()
        if not user or task not in TASK_TYPES or result not in OUTCOMES:
            return False
        if qual not in QUALITIES:
            qual = "clean"
        root = _user_dir(user)
        if root is None:
            return False
        try:
            root.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False
        entry = {
            "task": task,
            "tools": _clean_sequence(tools),
            "outcome": result,
            "quality": qual,
            "tier": str(tier or "")[:64],
            "signals": {str(k)[:32]: _cap_value(v) for k, v in dict(signals or {}).items()},
            "cost": {str(k)[:32]: _cap_value(v) for k, v in dict(cost or {}).items()},
            "ts": time.time(),
        }
        try:
            from services.storage import path_lock as _plock
        except Exception:
            _plock = None
        try:
            if _plock is None:
                with open(root / EXPERIENCE_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            else:
                with _plock(root / EXPERIENCE_FILE):
                    with open(root / EXPERIENCE_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            logger.debug("experience append failed", exc_info=True)
            return False
        _prune_episodes(user)
        try:
            from services.obs import record_lesson_event as _emit
            _emit("episode")
        except Exception:
            logger.debug("lesson episode metric failed", exc_info=True)
        # Mine lazily: counting ≤500 tiny records is sub-millisecond work,
        # amortized over MINE_EVERY_EPISODES turns.
        try:
            state = _load_state(user)
            since = int(state.get("episodes_since_mine", 0) or 0) + 1
            if since >= MINE_EVERY_EPISODES:
                mine_lessons(user)
                return True
            state["episodes_since_mine"] = since
            _save_state(user, state)
        except Exception:
            logger.debug("experience mine scheduling failed", exc_info=True)
        return False
    except Exception:
        logger.debug("record_episode failed", exc_info=True)
        return False


def amend_last_episode(user_id: str, task_type: str, tools: Any, quality: str) -> bool:
    """Refine the most recent matching episode's quality (never raises).

    Same-turn verdicts (a format repair) refine rather than duplicate:
    one turn stays one episode, so support can never inflate from a
    single turn. Matches the latest row with the same task and tool
    sequence (within the recent tail); no match is a silent no-op.
    Returns True when an episode was amended.
    """
    try:
        user = str(user_id or "").strip()
        task = str(task_type or "").strip().lower()
        qual = str(quality or "").strip().lower()
        seq = _clean_sequence(tools)
        if not user or task not in TASK_TYPES or qual not in QUALITIES:
            return False
        root = _user_dir(user)
        if root is None:
            return False
        path = root / EXPERIENCE_FILE
        if not path.is_file():
            return False
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return False
        target: Optional[int] = None
        for idx in range(len(lines) - 1, max(-1, len(lines) - 201), -1):
            try:
                entry = json.loads(lines[idx])
            except Exception:
                logger.debug("amend line parse failed", exc_info=True)
                continue
            if (isinstance(entry, dict)
                    and str(entry.get("task", "")) == task
                    and list(entry.get("tools", []) or []) == seq):
                target = idx
                break
        if target is None:
            return False
        entry = json.loads(lines[target])
        if not isinstance(entry, dict):
            return False
        entry["quality"] = qual
        lines[target] = json.dumps(entry, ensure_ascii=False) + "\n"
        try:
            from services.storage import path_lock as _plock
        except Exception:
            _plock = None
        tmp = _tmp_for(path, EXPERIENCE_FILE)
        try:
            if _plock is None:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                os.replace(tmp, path)
            else:
                with _plock(path):
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.writelines(lines)
                    os.replace(tmp, path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                logger.debug("amend tmp cleanup failed", exc_info=True)
            raise
        try:
            from services.obs import record_lesson_event as _emit
            _emit("amended")
        except Exception:
            logger.debug("lesson amended metric failed", exc_info=True)
        return True
    except Exception:
        logger.debug("amend_last_episode failed", exc_info=True)
        return False


def record_counter_evidence(user_id: str, task_type: str, tools: Any,
                            kind: str = "regenerated") -> bool:
    """Record later user rejection of a completed strategy (never raises).

    A regenerate means the user discarded the answer wholesale — strong
    negative evidence against that turn's tool sequence, appended as a
    disputed ok-episode (it DID complete; the strategy is what's
    disputed). Only fires for turns that actually used tools.
    """
    try:
        seq = _clean_sequence(tools)
        if not seq:
            return False
        return record_episode(
            user_id, task_type, seq, "ok",
            signals={"counter_evidence": str(kind or "regenerated")[:32]},
            quality="disputed")
    except Exception:
        logger.debug("record_counter_evidence failed", exc_info=True)
        return False


def _load_state(user_id: str) -> Dict[str, Any]:
    """Lesson store: {lessons: [...], episodes_since_mine: n} (never raises)."""
    try:
        root = _user_dir(str(user_id or ""))
        if root is None:
            return {"lessons": [], "episodes_since_mine": 0}
        path = root / LESSONS_FILE
        if not path.is_file():
            return {"lessons": [], "episodes_since_mine": 0}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"lessons": [], "episodes_since_mine": 0}
        lessons = data.get("lessons", [])
        clean: List[Dict[str, Any]] = []
        for lesson in lessons if isinstance(lessons, list) else []:
            fixed = _clean_lesson(lesson)
            if fixed is not None:
                clean.append(fixed)
        return {"lessons": clean,
                "episodes_since_mine": int(data.get("episodes_since_mine", 0) or 0)}
    except Exception:
        return {"lessons": [], "episodes_since_mine": 0}


def _clean_lesson(lesson: Any) -> Optional[Dict[str, Any]]:
    """Validate one stored lesson; None when unusable (never raises)."""
    try:
        if not isinstance(lesson, dict):
            return None
        task = str(lesson.get("task", "") or "").strip().lower()
        seq = _clean_sequence(lesson.get("sequence"))
        status = str(lesson.get("status", "") or "").strip().lower()
        if task not in TASK_TYPES or not seq:
            return None
        if status not in ("candidate", "trusted", "disabled"):
            status = "candidate"
        return {
            "id": f"{task}:{','.join(seq)}",
            "task": task,
            "sequence": seq,
            "support": max(0.0, float(lesson.get("support", 0) or 0)),
            "oppose": max(0, int(lesson.get("oppose", 0) or 0)),
            "status": status,
            "updated_ts": float(lesson.get("updated_ts", 0) or 0),
        }
    except Exception:
        return None


def _save_state(user_id: str, state: Dict[str, Any]) -> bool:
    """Atomically persist the lesson store (never raises)."""
    try:
        root = _user_dir(str(user_id or ""))
        if root is None:
            return False
        root.mkdir(parents=True, exist_ok=True)
        path = root / LESSONS_FILE
        try:
            from services.storage import path_lock as _plock
        except Exception:
            _plock = None
        tmp = _tmp_for(path, LESSONS_FILE)
        try:
            if _plock is None:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"lessons": state.get("lessons", []),
                               "episodes_since_mine": int(state.get("episodes_since_mine", 0) or 0)},
                              f, ensure_ascii=False)
                os.replace(tmp, path)
            else:
                with _plock(path):
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump({"lessons": state.get("lessons", []),
                                   "episodes_since_mine": int(state.get("episodes_since_mine", 0) or 0)},
                                  f, ensure_ascii=False)
                    os.replace(tmp, path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                logger.debug('experience tmp cleanup failed', exc_info=True)
            raise
        return True
    except Exception:
        logger.debug("experience save failed", exc_info=True)
        return False


def mine_lessons(user_id: str) -> List[Dict[str, Any]]:
    """Distill episodes into candidate/trusted lessons (never raises).

    Groups recent successful episodes by (task, tool sequence); each
    group is a candidate with support/oppose counts (oppose = failed or
    degraded episodes with the same shape). Trust needs MIN_SUPPORT
    with a MARGIN_RATIO lead over the strongest contradiction for that
    task. Disabled lessons stay disabled whatever the evidence says.
    Returns the full lesson list.
    """
    try:
        user = str(user_id or "").strip()
        if not user:
            return []
        now = time.time()
        support: Dict[str, int] = {}
        oppose: Dict[str, int] = {}
        for ep in _read_episodes(user):
            try:
                if not isinstance(ep, dict):
                    continue
                if now - float(ep.get("ts", 0) or 0) > EXPERIENCE_TTL_SECONDS:
                    continue
                task = str(ep.get("task", "") or "").strip().lower()
                seq = _clean_sequence(ep.get("tools"))
                if task not in TASK_TYPES or not seq:
                    continue
                key = f"{task}:{','.join(seq)}"
                outcome = str(ep.get("outcome", "") or "")
                quality = str(ep.get("quality", "clean") or "").strip().lower()
                if quality not in QUALITIES:
                    quality = "clean"
                if outcome == "ok" and quality != "disputed":
                    # Clean first-try success counts fully; polished
                    # (reflection rewrite / format repair) counts half —
                    # the tools may be fine, but the turn was not clean.
                    support[key] = support.get(key, 0.0) + QUALITY_WEIGHT.get(quality, 1.0)
                else:
                    # Failures, degraded turns, and user-disputed strategies
                    # (regenerates) count against.
                    oppose[key] = oppose.get(key, 0) + 1
            except Exception:
                logger.debug('episode grouping failed', exc_info=True)
                continue
        # Strongest contradiction per (task, key): the best count of any
        # OTHER sequence shape for the same task. The key's own count
        # must never feed its rival (that made every leader unbeatable).
        counts = list(support.items()) + list(oppose.items())
        best_other: Dict[str, int] = {}
        for key, _count in counts:
            try:
                task = key.split(":", 1)[0]
                rival = 0
                for other, ocount in counts:
                    if other == key or not other.startswith(task + ":"):
                        continue
                    if ocount > rival:
                        rival = ocount
                best_other[key] = rival
            except Exception:
                logger.debug('rival computation failed', exc_info=True)
                continue
        state = _load_state(user)
        previous = {str(l.get("id", "")): l for l in state.get("lessons", [])
                    if isinstance(l, dict)}
        lessons: List[Dict[str, Any]] = []
        for key in set(list(support) + list(oppose)):
            try:
                task, seq_str = key.split(":", 1)
                seq = seq_str.split(",") if seq_str else []
                if not seq:
                    continue
                sup = support.get(key, 0)
                opp = oppose.get(key, 0)
                rival = best_other.get(key, 0)
                trusted = (sup >= LESSON_MIN_SUPPORT
                           and sup >= LESSON_MARGIN_RATIO * max(rival, opp, 1)
                           and sup > opp)
                prev = previous.get(key, {})
                status = str(prev.get("status", "") or "")
                if status == "disabled":
                    final = "disabled"  # never auto re-enable
                elif trusted:
                    final = "trusted"
                else:
                    final = "candidate"
                lessons.append({
                    "id": key,
                    "task": task,
                    "sequence": seq,
                    "support": sup,
                    "oppose": opp,
                    "status": final,
                    "updated_ts": now,
                })
            except Exception:
                logger.debug("lesson build failed", exc_info=True)
                continue
        # Keep disabled lessons with no fresh evidence (audit trail).
        for pid, plesson in previous.items():
            try:
                if (isinstance(plesson, dict)
                        and plesson.get("status") == "disabled"
                        and pid not in {str(l.get("id", "")) for l in lessons}):
                    lessons.append(dict(plesson))
            except Exception:
                logger.debug("disabled lesson carry failed", exc_info=True)
                continue
        state = {"lessons": lessons, "episodes_since_mine": 0}
        _save_state(user, state)
        try:
            from services.obs import record_lesson_event as _emit
            _emit("mined")
            for lesson in lessons:
                if lesson.get("status") == "trusted":
                    _emit("trusted")
        except Exception:
            logger.debug("lesson mined metric failed", exc_info=True)
        return lessons
    except Exception:
        logger.debug("mine_lessons failed", exc_info=True)
        return []


def get_lessons(user_id: str, status: str = "") -> List[Dict[str, Any]]:
    """Stored lessons, optionally filtered by status (never raises)."""
    try:
        lessons = _load_state(str(user_id or "")).get("lessons", [])
        want = str(status or "").strip().lower()
        if want:
            return [dict(l) for l in lessons
                    if isinstance(l, dict) and l.get("status") == want]
        return [dict(l) for l in lessons if isinstance(l, dict)]
    except Exception:
        return []


def get_trusted_sequences(task_type: str, user_id: str) -> List[List[str]]:
    """Trusted tool sequences for a task (never raises)."""
    try:
        task = str(task_type or "").strip().lower()
        if task not in TASK_TYPES:
            return []
        return [list(l["sequence"]) for l in get_lessons(str(user_id or ""), "trusted")
                if isinstance(l, dict) and l.get("task") == task
                and isinstance(l.get("sequence"), list)]
    except Exception:
        return []


def disable_lesson(user_id: str, lesson_id: str) -> bool:
    """Permanently disable a lesson (never auto re-enabled)."""
    try:
        user = str(user_id or "").strip()
        lid = str(lesson_id or "").strip()
        if not user or not lid:
            return False
        state = _load_state(user)
        found = False
        for lesson in state.get("lessons", []):
            if isinstance(lesson, dict) and lesson.get("id") == lid:
                lesson["status"] = "disabled"
                lesson["updated_ts"] = time.time()
                found = True
        if not found:
            return False
        return _save_state(user, state)
    except Exception:
        return False


def delete_lesson(user_id: str, lesson_id: str) -> bool:
    """Remove a lesson entirely (never raises)."""
    try:
        user = str(user_id or "").strip()
        lid = str(lesson_id or "").strip()
        if not user or not lid:
            return False
        state = _load_state(user)
        kept = [l for l in state.get("lessons", [])
                if not (isinstance(l, dict) and l.get("id") == lid)]
        if len(kept) == len(state.get("lessons", [])):
            return False
        state["lessons"] = kept
        return _save_state(user, state)
    except Exception:
        return False
