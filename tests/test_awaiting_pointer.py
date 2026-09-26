"""Awaiting-pointer routing: bare acks resolve against the pointer, not the window.

Regression for the screenshot bug: teach Slide N -> unrelated Q answered
-> "ok" resumed Slide N+1 because a 10-message marker window outlived the
topic switch. The pointer (stamped on every assistant turn) is now the
single source of truth; the window is backfill-only for pre-pointer chats.
"""

import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _teach_msg(awaiting, content="lesson"):
    return {"role": "assistant", "content": content,
            "teaching": {"active": True, "file": "L",
                         "cursor": 10, "awaiting": awaiting, "v": 1}}


def _plain_msg(awaiting, content="answer"):
    return {"role": "assistant", "content": content,
            "teaching": {"active": False, "file": "",
                         "cursor": 0, "awaiting": awaiting, "v": 1}}


def _lesson(n):
    return (f"📘 FILE: Lecture_01.pptx\nSlides: {n}-{n}\n## Concept: G\n"
            f"**Source:** [slide {n}]\nWhat is S{n}?")


# --- precedence: pointer wins over window, both directions ---


def test_pointer_none_beats_live_window():
    """Screenshot reconstruction (routing level): unrelated answer stamped
    pointer-none, old lecture marker still in last 10 -> ok must NOT resume."""
    from backend.teach import _is_teaching_continuation

    hist = [
        {"role": "assistant", "content": _lesson(13),
         "teaching": {"active": True, "file": "Lecture_01.pptx",
                      "cursor": 13, "awaiting": "teaching:Lecture_01.pptx:13", "v": 1}},
        {"role": "user", "content": "I want a portfolio website, write the code"},
        {"role": "assistant", "content": "Here is your portfolio plan...",
         "teaching": {"active": False, "file": "",
                      "cursor": 0, "awaiting": "none", "v": 1}},
    ]
    assert _is_teaching_continuation("ok", hist) is False


def test_pointer_teaching_beats_flushed_window():
    """Pointer-teaching + window flushed of markers (10+ plain turns, no
    recall question pending) -> ok still continues via pointer."""
    from backend.teach import _is_teaching_continuation

    hist = [{"role": "assistant",
             "content": f"plain turn {i}",
             "teaching": {"active": False, "file": "", "cursor": 0,
                          "awaiting": "none", "v": 1}} for i in range(10)]
    hist.append(_teach_msg("teaching:Lecture_01.pptx:13", "still on slide 13?"))
    assert _is_teaching_continuation("ok", hist) is True


def test_unrelated_ok_answers_unrelated_thread():
    """End-to-end routing: teach N -> unrelated Q answered -> ok routes to
    normal path (no teaching flag, no Slide N+1, no Do NOT advance)."""
    from backend.teach import _is_teaching_continuation

    hist = [
        {"role": "assistant", "content": _lesson(10),
         "teaching": {"active": True, "file": "L",
                      "cursor": 10, "awaiting": "teaching:L:10", "v": 1}},
        {"role": "user", "content": "what is 2+2?"},
        {"role": "assistant", "content": "2+2 is 4.",
         "teaching": {"active": False, "file": "",
                      "cursor": 0, "awaiting": "none", "v": 1}},
    ]
    assert _is_teaching_continuation("ok", hist) is False
    assert _is_teaching_continuation("Next", hist) is False


# --- carry-forward: fallbacks preserve the pointer ---


def test_fallback_carries_pointer_forward():
    from backend.teach import _pointer_in_recent
    from backend.flow.turns import _prior_awaiting

    hist = [
        _teach_msg("teaching:Lecture_01.pptx:13", _lesson(13)),
        {"role": "assistant", "content": "Whenever you're ready...",
         "teaching": {"active": False, "file": "", "cursor": 0,
                      "awaiting": "teaching:Lecture_01.pptx:13", "v": 1}},
    ]
    assert _prior_awaiting(hist) == "teaching:Lecture_01.pptx:13"
    assert _pointer_in_recent(hist)[0] == "teaching:Lecture_01.pptx:13"


def test_pre_pointer_chat_derives_legacy_once():
    """No v key anywhere -> backfill derives teaching:{file}:{cursor}."""
    from backend.flow.turns import _prior_awaiting

    hist = [{"role": "assistant", "content": _lesson(10)}]
    assert _prior_awaiting(hist) == "teaching:Lecture_01.pptx:10"


# --- storage contract ---


def test_cleaner_round_trips_pointer():
    from services.storage.cleaners import clean_messages

    msgs = [_teach_msg("teaching:L:13"), _plain_msg("none"),
            {"role": "assistant", "content": _lesson(9),
             "teaching": {"active": True, "file": "L", "cursor": 9}}]
    cleaned = clean_messages(msgs)
    assert cleaned[0]["teaching"]["awaiting"] == "teaching:L:13"
    assert cleaned[0]["teaching"]["v"] == 1
    assert cleaned[1]["teaching"]["awaiting"] == "none"
    # Pre-pointer shape survives without invented pointer (backfill intact).
    assert "awaiting" not in cleaned[2]["teaching"]
    assert "v" not in cleaned[2]["teaching"]


def test_assistant_meta_requires_awaiting():
    import pytest

    from backend.flow.stages import _assistant_meta

    with pytest.raises(TypeError):
        _assistant_meta([], [], False, False, "t")  # type: ignore[call-arg]
    meta = _assistant_meta([], [], False, False, "t", awaiting="none")
    assert meta["teaching"]["awaiting"] == "none"
    assert meta["teaching"]["v"] == 1


def test_all_meta_writers_pass_awaiting_and_only_helper_makes_ambiguous():
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    # Definition itself requires awaiting (keyword-only, no default).
    stree = ast.parse((root / "backend/flow/stages.py").read_text(encoding="utf-8"))
    defs = [n for n in ast.walk(stree)
            if isinstance(n, ast.FunctionDef) and n.name == "_assistant_meta"]
    assert len(defs) == 1
    kwonly = [a.arg for a in defs[0].args.kwonlyargs]
    defaults = defs[0].args.kw_defaults
    idx = kwonly.index("awaiting")
    assert defaults[idx] is None, "awaiting must have no default"
    # Every writer passes it.
    for rel in ("backend/flow/turns.py",):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(getattr(n, "func", None), ast.Name)
                 and getattr(n.func, "id", "") == "_assistant_meta"]
        assert calls, rel
        for call in calls:
            names = [kw.arg for kw in call.keywords]
            assert "awaiting" in names, f"{rel}:{call.lineno} missing awaiting"
    constructors = []
    for path in list((root / "backend").rglob("*.py")) + list((root / "agent").rglob("*.py")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or s.startswith('"') or s.startswith("'"):
                continue  # comments/docstrings only mention it
            if 'return "ambiguous:' in line or "return 'ambiguous:" in line:
                constructors.append(f"{path.relative_to(root)}:{i}")
    assert constructors and all(
        c.startswith("backend\\flow\\turns.py:") or c.startswith("backend/flow/turns.py")
        for c in constructors), constructors
