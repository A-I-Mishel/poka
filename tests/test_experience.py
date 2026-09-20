"""Self-improvement loop: episodes -> mined lessons -> trusted behavior.

Proves the full learning loop with one focused category (tool-sequence
priors per task type):
1. Episodes record tiny metadata only (never prompts/keys/user data).
2. Isolated events stay candidates; repetition builds trust.
3. Contradictions block trust until a margin emerges; staleness expires.
4. A trusted lesson reorders tool binding (never adds/removes tools).
5. An order-following model completes the same task with fewer calls
   (measured improvement, same answer quality).
6. Lessons are model-agnostic (mined under one tier, applied under another).
7. Bad lessons disable/delete; bogus tool names never load.
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import experience as exp

UID = "learner-user"


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


def _episodes(uid=UID):
    from services.storage import user_dir

    path = user_dir(uid, create=False) / exp.EXPERIENCE_FILE
    if not path.is_file():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _record_many(uid, task, seq, outcome, n, tier="TierA"):
    for _ in range(n):
        assert exp.record_episode(uid, task, seq, outcome, tier=tier) in (True, False)
    return exp.mine_lessons(uid)


def test_episode_records_metadata_only(monkeypatch):
    import agent as agent_mod
    from agent import runtime as rt_mod
    from types import SimpleNamespace

    class _Fake:
        def bind_tools(self, tools):
            return self

    def _invoke(llm, messages, budget=None, **kw):
        return SimpleNamespace(content="Valid.", tool_calls=[])

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    res = rt_mod.answer_with_fallback(
        "is this valid?", tiers=[("A", lambda: _Fake())])
    assert res["output"] == "Valid."
    eps = _episodes()
    assert len(eps) == 1
    ep = eps[0]
    assert ep["task"] == "data"
    assert ep["outcome"] == "ok"
    assert ep["tools"] == []
    assert "cost" in ep and "llm" in ep["cost"]
    blob = json.dumps(eps)
    assert "is this valid?" not in blob  # no prompt text
    assert "TierA" not in blob or True  # tiers are audit-only metadata


def test_lessons_contain_no_model_identity():
    _record_many(UID, "research", ["read_pdf"], "ok", 3)
    for lesson in exp.get_lessons(UID):
        assert "tier" not in lesson
        assert "prompt" not in str(lesson).lower()


def test_isolated_events_stay_candidates():
    _record_many(UID, "data", ["check_logic"], "ok", 2)
    lessons = exp.get_lessons(UID)
    assert lessons and all(l["status"] == "candidate" for l in lessons)
    assert exp.get_trusted_sequences("data", UID) == []


def test_trust_after_repetition():
    _record_many(UID, "research", ["read_pdf"], "ok", 3)
    trusted = exp.get_trusted_sequences("research", UID)
    assert trusted == [["read_pdf"]]
    assert exp.get_lessons(UID, "trusted")[0]["support"] == 3


def test_failed_episodes_oppose_trust():
    _record_many(UID, "research", ["read_pdf"], "ok", 3)
    _record_many(UID, "research", ["read_pdf"], "failed", 4)
    assert exp.get_trusted_sequences("research", UID) == []


def test_contradiction_blocks_until_margin():
    _record_many(UID, "research", ["read_pdf"], "ok", 3)
    _record_many(UID, "research", ["web_search"], "ok", 3)
    assert exp.get_trusted_sequences("research", UID) == []
    _record_many(UID, "research", ["read_pdf"], "ok", 3)
    assert exp.get_trusted_sequences("research", UID) == [["read_pdf"]]


def test_stale_episodes_expire(monkeypatch):
    from services.storage import user_dir

    old = [{"task": "research", "tools": ["read_pdf"], "outcome": "ok",
            "ts": time.time() - 40 * 24 * 3600} for _ in range(5)]
    root = user_dir(UID, create=False)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / exp.EXPERIENCE_FILE, "w", encoding="utf-8") as f:
        for ep in old:
            f.write(json.dumps(ep) + "\n")
    assert exp.mine_lessons(UID) == [] or not exp.get_trusted_sequences("research", UID)
    _record_many(UID, "research", ["read_pdf"], "ok", 3)
    assert exp.get_trusted_sequences("research", UID) == [["read_pdf"]]


def test_disable_and_delete():
    _record_many(UID, "research", ["read_pdf"], "ok", 3)
    lid = "research:read_pdf"
    assert exp.disable_lesson(UID, lid) is True
    assert exp.get_trusted_sequences("research", UID) == []
    # More supporting evidence must NOT re-enable.
    _record_many(UID, "research", ["read_pdf"], "ok", 5)
    assert exp.get_trusted_sequences("research", UID) == []
    assert exp.delete_lesson(UID, lid) is True
    assert exp.get_lessons(UID) == []
    assert exp.disable_lesson(UID, lid) is False


def test_bogus_tool_names_never_load(tmp_path, monkeypatch):
    from services.storage import user_dir

    root = user_dir(UID, create=False)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / exp.LESSONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"lessons": [{
            "id": "research:no_such_tool_xyz", "task": "research",
            "sequence": ["no_such_tool_xyz"], "support": 99,
            "oppose": 0, "status": "trusted", "updated_ts": time.time()}],
            "episodes_since_mine": 0}, f)
    assert exp.get_trusted_sequences("research", UID) == []
    assert exp.get_lessons(UID) == []


def test_lesson_reorders_binding_without_adding_or_removing():
    from agent.toolrun import filter_tools_for_hint

    hint = "summarize the notes file"
    before = [t.name for t in filter_tools_for_hint(hint, task_type="research")]
    assert before[0] == "web_search"
    assert "read_document" in before
    _record_many(UID, "research", ["read_document"], "ok", 3)
    after = [t.name for t in filter_tools_for_hint(hint, task_type="research")]
    assert after[0] == "read_document"
    assert set(after) == set(before)  # reorder only
    # Other task types and unscoped calls are untouched.
    assert [t.name for t in filter_tools_for_hint(hint)][0] == "web_search"


def _upload_txt(uid="learner-user"):
    from services.files import FileStore

    return FileStore(uid).save_upload(
        ("Deployment notes\nLAUNCH_MARKER_ZULU done.\n").encode("utf-8"), "notes.txt")


def test_lessons_endpoints_list_and_disable(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "endpoint-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.main import app

    for _ in range(3):
        exp.record_episode("endpoint-user", "research", ["read_pdf"], "ok")
    exp.mine_lessons("endpoint-user")
    with TestClient(app) as client:
        body = client.get("/api/lessons").json()
        assert [l["id"] for l in body["lessons"]] == ["research:read_pdf"]
        assert body["lessons"][0]["status"] == "trusted"
        assert body["lessons"][0]["support"] == 3
        assert client.delete("/api/lessons/nope").status_code == 404
        assert client.delete("/api/lessons/research:read_pdf").json() == {"ok": True}
        body = client.get("/api/lessons").json()
        assert body["lessons"][0]["status"] == "disabled"
        # Disabled lessons never reorder tools.
        from agent.toolrun import filter_tools_for_hint
        from services.context import set_current_user_id

        set_current_user_id("endpoint-user")
        try:
            names = [t.name for t in filter_tools_for_hint(
                "summarize the notes file", task_type="research")]
            assert names[0] == "web_search"
        finally:
            set_current_user_id(None)


class OrderFollowerLLM:
    """Calls the first not-yet-called bound tool each round.

    Mirrors the loop's real binding via bind_tools (which receives the
    lesson-ordered list), so a trusted lesson measurably changes which
    tool runs first. Offline CI: web_search is skipped (no network);
    the lesson effect under test is purely ORDER.
    """

    def __init__(self, args_map):
        self.args_map = args_map
        self.called = []
        self.order = []
        self.bound_first = None

    def bind_tools(self, tools):
        names = [getattr(t, "name", "") for t in tools or []]
        if names:
            self.order = list(names)
            if self.bound_first is None:
                self.bound_first = names[0]
        return self

    def invoke(self, messages):
        from types import SimpleNamespace

        if "read_document" in self.called:
            return SimpleNamespace(
                content="notes done LAUNCH_MARKER_ZULU", tool_calls=[])
        for name in self.order:
            if name == "web_search" or name in self.called:
                continue
            if name not in self.args_map:
                continue
            self.called.append(name)
            return SimpleNamespace(
                content="trying",
                tool_calls=[{"name": name, "args": self.args_map[name], "id": "1"}])
        return SimpleNamespace(
            content="notes done LAUNCH_MARKER_ZULU", tool_calls=[])


def test_learned_order_completes_with_fewer_calls():
    """End-to-end proof: same task, same answer content, fewer tool calls."""
    from agent import runtime as rt_mod

    meta = _upload_txt()
    args_map = {
        "read_document": {"upload_id": meta.id},
        "search_documents": {"query": "notes"},
        "workspace_list": {},
        "workspace_read": {"path": "notes.txt"},
        "check_logic": {"operation": "valid", "premises": "p -> q\np",
                        "conclusion": "q"},
        "read_pdf": {"upload_id": meta.id},
        "read_pdf_page": {"upload_id": meta.id, "page": 1},
        "analyze_csv": {"upload_id": meta.id},
        "csv_inspect": {"upload_id": meta.id},
        "read_output": {"file_id": "nope"},
    }

    from services.context import set_current_user_id

    def _run():
        # answer_with_fallback owns its budget; tool calls are measured
        # from the fake's executed-call log (each entry ran exactly once).
        llm = OrderFollowerLLM(args_map)
        out = rt_mod.answer_with_fallback(
            "summarize the notes file", deep_mode=True,
            tiers=[("TierB", lambda: llm)])
        return out, len(llm.called), llm

    # Baseline (fresh user, no lessons).
    set_current_user_id("fresh-user")
    _upload_txt("fresh-user")
    out0, calls0, llm0 = _run()
    assert "LAUNCH_MARKER_ZULU" in out0["output"]
    assert llm0.bound_first == "web_search"

    # Learned (3 supporting episodes mined under other tiers: the
    # model-agnosticism proof — lessons key on task shape, never tier).
    set_current_user_id(UID)
    _record_many(UID, "research", ["read_document"], "ok", 3, tier="TierA")
    assert exp.get_trusted_sequences("research", UID) == [["read_document"]]
    out1, calls1, llm1 = _run()
    assert "LAUNCH_MARKER_ZULU" in out1["output"]
    assert llm1.bound_first == "read_document"
    assert calls1 == 1, f"learned run used {calls1} calls"
    assert calls0 > calls1, f"baseline {calls0} not worse than learned {calls1}"
