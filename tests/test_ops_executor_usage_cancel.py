"""Milestone 3 tests: ops endpoint, executor split, usage/latency, cancel."""

import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from agent.budget import TurnCancelled
from agent.executor import ExecutorBusyError
from services import context as ctx


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("m3-user")
    ctx.set_limit_key("m3-user")
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
    try:
        from agent import cascade as _cascade

        _cascade._TIER_LAT_EMA.clear()
    except Exception:
        pass
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        if self.script:
            item = self.script.pop(0)
            text, calls = item if isinstance(item, tuple) else (item, [])
        else:
            text, calls = ("ok", [])
        return SimpleNamespace(content=text, tool_calls=calls)


# --- ops endpoint ------------------------------------------------


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_USER_ID", "ops-user")
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app)


def test_ops_tiers_lists_and_resets(tmp_path, monkeypatch):
    from agent import cascade as _cascade

    client = _client(tmp_path, monkeypatch)
    res = client.get("/api/ops/tiers")
    assert res.status_code == 200, res.text
    names = [t["name"] for t in res.json()["tiers"]]
    assert "Groq" in names
    entry = next(t for t in res.json()["tiers"] if t["name"] == "Groq")
    assert entry["configured"] in (True, False)
    assert entry["skipped"] is False

    _cascade._record_tier_failure("Groq", "rate_limit", Exception("429 slow down"))
    cooled = client.get("/api/ops/tiers").json()
    groq = next(t for t in cooled["tiers"] if t["name"] == "Groq")
    assert groq["skipped"] is True
    assert groq["cooldown_remaining_s"] > 0
    assert groq["last_error_kind"] == "rate_limit"

    reset = client.post("/api/ops/tiers/reset", json={"tier": "Groq"})
    assert reset.status_code == 200 and reset.json()["cleared"] >= 1
    fresh = client.get("/api/ops/tiers").json()
    assert next(t for t in fresh["tiers"] if t["name"] == "Groq")["skipped"] is False

    reset_all = client.post("/api/ops/tiers/reset", json={})
    assert reset_all.status_code == 200


# --- executor split ------------------------------------------------


def test_model_pool_separate_from_tool_pool():
    import agent.executor as executor

    assert executor._bounded_model_pool is not executor._bounded_pool
    assert len(executor._bounded_model_pool._threads) == 32
    assert len(executor._bounded_pool._threads) == 8


def test_model_pool_saturation_isolated(monkeypatch):
    import agent.executor as executor

    gate = threading.Event()
    tiny = executor._BoundedExecutor(1, "test-model")
    first = tiny.submit(gate.wait)
    deadline = time.time() + 5.0
    while not first.running():
        assert time.time() < deadline
        time.sleep(0.01)
    for _ in range(2):
        tiny.submit(lambda: None)
    monkeypatch.setattr(executor, "_bounded_model_pool", tiny)
    try:
        with pytest.raises(ExecutorBusyError):
            executor._call_bounded(lambda: 1, timeout=5.0, what="m",
                                   pool=executor._bounded_model_pool)
        # Tool pool untouched: still serves.
        assert executor._call_bounded(lambda: 42, timeout=5.0, what="t") == 42
    finally:
        monkeypatch.undo()
        gate.set()


def test_tool_pool_still_default(monkeypatch):
    import agent.executor as executor

    assert executor._call_bounded(lambda: 7, timeout=5.0, what="t") == 7


# --- usage + latency ------------------------------------------------


def test_usage_metadata_recorded():
    import agent.executor as executor
    from services.metrics import REGISTRY

    class UsageLLM(FakeLLM):
        def invoke(self, messages):
            self.calls.append(messages)
            return SimpleNamespace(
                content="hi",
                tool_calls=[],
                usage_metadata={"input_tokens": 11, "output_tokens": 4})

    before_in = REGISTRY.get_sample_value(
        "pluto_llm_tokens_total", {"tier": "usage-tier", "direction": "prompt"}) or 0.0
    executor._invoke_bounded(UsageLLM([]), "hi", timeout=10.0, tier_name="usage-tier")
    after_in = REGISTRY.get_sample_value(
        "pluto_llm_tokens_total", {"tier": "usage-tier", "direction": "prompt"})
    after_out = REGISTRY.get_sample_value(
        "pluto_llm_tokens_total", {"tier": "usage-tier", "direction": "completion"})
    assert (after_in or 0.0) - before_in == 11.0
    assert (after_out or 0.0) == 4.0


def test_slow_tier_demoted_not_excluded():
    from agent import cascade as _cascade

    table = [("fast-a", lambda: None), ("slowpoke", lambda: None), ("fast-b", lambda: None)]
    for _ in range(5):
        _cascade._record_latency("slowpoke", 120.0)
    for _ in range(5):
        _cascade._record_latency("fast-a", 1.0)
        _cascade._record_latency("fast-b", 2.0)
    order = [n for n, _ in _cascade._usable_tiers(None, table, prefer_fast=True)]
    assert order == ["fast-a", "fast-b", "slowpoke"]
    # Default path unchanged; cold tiers never penalized.
    order_default = [n for n, _ in _cascade._usable_tiers(None, table)]
    assert order_default == ["fast-a", "slowpoke", "fast-b"]
    assert _cascade._is_slow_tier("never-seen") is False


# --- cancellation --------------------------------------------------


def test_cancel_before_start_aborts_without_tools():
    from agent.toolrun import run_tool_loop

    fake = FakeLLM([("", [{"name": "check_logic", "args": {}, "id": "1"}])])
    with pytest.raises(TurnCancelled):
        run_tool_loop(fake, "hi", [], cancel=lambda: True)
    assert fake.calls == []


def test_cancel_midloop_propagates_partial_tools():
    from agent.toolrun import run_tool_loop

    state = {"cancel": False}
    used = []
    fake = FakeLLM([
        ("", [{"name": "check_logic", "args": {"operation": "table",
                                              "formula": "p -> q"}, "id": "1"}]),
        ("second answer", []),
    ])
    with pytest.raises(TurnCancelled):
        run_tool_loop(fake, "hi", [], used_tools=used,
                      cancel=lambda: state["cancel"],
                      on_progress=lambda _t: state.update(cancel=True))
    assert used == ["check_logic"]


def test_cancel_never_cools_tiers():
    from agent.toolrun import run_tool_loop

    fake = FakeLLM(["draft"])
    with pytest.raises(TurnCancelled):
        run_tool_loop(fake, "hi", [], cancel=lambda: True)
    assert agent._TIER_FAILS == {}
    assert agent._TIER_SKIP_UNTIL == {}


def test_run_chat_cancel_persists_nothing(tmp_path, monkeypatch):
    import agent as agent_mod
    from backend.chatflow import run_chat
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore

    ctx_obj = UserContext(user_id="cancel-user", user_store=UserStore("cancel-user"),
                          file_store=FileStore("cancel-user"),
                          limit_key="cancel-user", source="env")

    def _boom(user_input, history=None, **kwargs):
        raise TurnCancelled("gone")

    monkeypatch.setattr(agent_mod, "answer_with_fallback", _boom)
    with pytest.raises(TurnCancelled):
        run_chat(ctx_obj, "hello there", cancel=lambda: True)
    stored, _ = ctx_obj.user_store.load_chats()
    assert stored.get("current", []) == []
