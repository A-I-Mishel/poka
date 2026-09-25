"""Quality-weighted evidence: clean counts fully, polish half, rejection opposes.

Slice 2: the question is no longer "did the turn finish" but "was the
strategy good". Reflection rewrites and format repairs downgrade an
episode to polished (half support, same turn — never a duplicate row);
user regeneration appends counter-evidence against the discarded
strategy; weak evidence alone never trusts; trust thresholds,
margins, TTL, and disable/delete safeguards behave identically.
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import experience as exp

UID = "quality-user"


@pytest.fixture(autouse=True)
def _vault(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", UID)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from services.context import set_current_user_id, set_limit_key

    set_current_user_id(UID)
    set_limit_key(UID)
    yield
    set_current_user_id(None)
    set_limit_key(None)


def _rows():
    from services.storage import user_dir

    path = user_dir(UID, create=False) / exp.EXPERIENCE_FILE
    if not path.is_file():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _mine(task, seq, outcome, n, quality="clean"):
    for _ in range(n):
        exp.record_episode(UID, task, seq, outcome, quality=quality)
    return exp.mine_lessons(UID)


def test_polished_counts_half():
    _mine("research", ["read_pdf"], "ok", 2, quality="polished")
    lessons = exp.get_lessons(UID)
    assert lessons and lessons[0]["support"] == 1.0
    assert lessons[0]["status"] == "candidate"


def test_weak_evidence_alone_never_trusts():
    _mine("research", ["read_pdf"], "ok", 3, quality="polished")
    assert exp.get_trusted_sequences("research", UID) == []
    _mine("research", ["read_pdf"], "ok", 2)  # +2 clean = 3.5 total
    assert exp.get_trusted_sequences("research", UID) == [["read_pdf"]]


def test_repair_amends_in_place_without_duplicating():
    exp.record_episode(UID, "research", ["read_pdf"], "ok")
    assert len(_rows()) == 1
    assert exp.amend_last_episode(UID, "research", ["read_pdf"], "polished") is True
    rows = _rows()
    assert len(rows) == 1, "one turn stays one episode"
    assert rows[0]["quality"] == "polished"
    exp.mine_lessons(UID)
    assert exp.get_lessons(UID)[0]["support"] == 0.5


def test_amend_no_match_is_silent_noop():
    assert exp.amend_last_episode(UID, "research", ["read_pdf"], "polished") is False
    exp.record_episode(UID, "research", ["web_search"], "ok")
    assert exp.amend_last_episode(UID, "research", ["read_pdf"], "polished") is False
    assert _rows()[0]["quality"] == "clean"


def test_regenerate_demotes_trusted_lesson(tmp_path, monkeypatch):
    from backend.deps import UserContext
    from backend.flow import turns as turns_mod
    from services.files import FileStore
    from services.storage import UserStore

    _mine("research", ["read_document"], "ok", 3)
    assert exp.get_trusted_sequences("research", UID) == [["read_document"]]

    ctx = UserContext(user_id=UID, user_store=UserStore(UID),
                      file_store=FileStore(UID), limit_key=UID, source="env")
    store = ctx.user_store
    store.save_chats([], [
        {"role": "user", "content": "summarize the research paper", "time": "t"},
        {"role": "assistant", "content": "old answer", "time": "t",
         "tools": ["read_document"]},
    ])

    def _fresh(*args, **kwargs):
        return ({"role": "assistant", "content": "new answer", "time": "t2"},
                "TierB", "research", None, None)

    monkeypatch.setattr(turns_mod, "_complete_turn_guarded", _fresh)
    for _ in range(3):
        turns_mod.regenerate_chat(ctx, 1)
    exp.mine_lessons(UID)
    lessons = exp.get_lessons(UID)
    assert lessons[0]["support"] == 3.0
    assert lessons[0]["oppose"] == 3
    assert lessons[0]["status"] == "candidate", "sustained rejection dethrones"
    assert exp.get_trusted_sequences("research", UID) == []


def test_single_regen_slows_but_keeps_trust():
    _mine("research", ["read_document"], "ok", 3)
    exp.record_counter_evidence(UID, "research", ["read_document"])
    exp.mine_lessons(UID)
    lesson = exp.get_lessons(UID)[0]
    assert (lesson["support"], lesson["oppose"]) == (3.0, 1)
    assert lesson["status"] == "trusted"


def test_counter_evidence_needs_tools_and_task():
    assert exp.record_counter_evidence(UID, "research", []) is False
    assert exp.record_counter_evidence(UID, "nonsense-task", ["read_pdf"]) is False
    assert exp.record_counter_evidence(UID, "research", ["bogus-tool"]) is False


def test_repair_path_amends_runtime_episode(tmp_path, monkeypatch):
    from backend.flow import turns as turns_mod

    ctx_uid = UID
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore

    ctx = UserContext(user_id=ctx_uid, user_store=UserStore(ctx_uid),
                      file_store=FileStore(ctx_uid), limit_key=ctx_uid,
                      source="env")

    # Simulate the runtime-recorded episode (completion itself is stubbed
    # here; the wiring under test is repair -> amend).
    exp.record_episode(UID, "research", ["read_pdf"], "ok")

    def _complete(*args, **kwargs):
        return ({"role": "assistant", "content": "draft", "time": "t",
                 "tools": ["read_pdf"]}, "T", "research", None, None)

    monkeypatch.setattr(turns_mod, "_complete_turn_guarded", _complete)
    monkeypatch.setattr(
        turns_mod, "_maybe_repair_teaching_turn",
        lambda send_text, content, tier, on_token=None, on_reset=None,
        budget=None, on_progress=None: (content + " [fixed]", True, []))
    out = turns_mod.run_chat(ctx, "teach me the research slides")
    assert out["message"]["content"].endswith("[fixed]")
    rows = _rows()
    assert len(rows) == 1, "repair refines, never duplicates"
    assert rows[0]["quality"] == "polished"


def test_pre_quality_rows_mine_as_clean(tmp_path):
    from services.storage import user_dir

    root = user_dir(UID, create=False)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / exp.EXPERIENCE_FILE, "w", encoding="utf-8") as f:
        for _ in range(3):
            f.write(json.dumps({"task": "research", "tools": ["read_pdf"],
                                "outcome": "ok", "ts": time.time()}) + "\n")
    exp.mine_lessons(UID)
    assert exp.get_trusted_sequences("research", UID) == [["read_pdf"]]


def test_no_rework_stays_clean(tmp_path, monkeypatch):
    import agent as agent_mod
    from agent import runtime as rt_mod
    from types import SimpleNamespace

    class _Fake:
        def bind_tools(self, tools):
            return self

    def _invoke(llm, messages, budget=None, **kw):
        return SimpleNamespace(content="simple", tool_calls=[])

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    res = rt_mod.answer_with_fallback(
        "is this valid?", tiers=[("A", lambda: _Fake())])
    assert res["output"] == "simple"
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["quality"] == "clean"


def test_reflection_rewrite_marks_polished(tmp_path, monkeypatch):
    import agent as agent_mod
    from agent import runtime as rt_mod
    from types import SimpleNamespace

    class _Fake:
        def bind_tools(self, tools):
            return self

    script = iter([
        SimpleNamespace(content="analysis failed midway", tool_calls=[]),
        SimpleNamespace(content="[IMPROVE] polished final analysis with sources",
                        tool_calls=[]),
    ])

    def _invoke(llm, messages, budget=None, **kw):
        return next(script)

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    res = rt_mod.answer_with_fallback(
        "summarize the research findings in depth with deep analysis",
        deep_mode=True, tiers=[("A", lambda: _Fake())])
    assert "polished final analysis" in res["output"]
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["quality"] == "polished", rows[0]
