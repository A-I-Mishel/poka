"""Tier attribution tests: active_tier names the final answer's producer.

Failover A->B->A must report A (not first-success-order B), and a
reflection rewrite must report the rewriter's tier, not the draft's.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from agent.toolrun import run_tool_loop


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()


class ScriptLLM:
    """Invoke-only double with a script of text|(text, tool_calls)."""

    def __init__(self, script):
        self._script = list(script)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        from types import SimpleNamespace

        item = self._script.pop(0) if self._script else "ok"
        text, calls = item if isinstance(item, tuple) else (item, [])
        return SimpleNamespace(content=text, tool_calls=calls)


class RaisingLLM(ScriptLLM):
    def invoke(self, messages):
        raise RuntimeError("tier is down")


def test_failover_attributes_final_round_tier():
    bogus = [{"name": "bogus-tool-xyz", "args": {}, "id": "1"}]
    states = {
        "tier-a": ScriptLLM([("thinking on a", bogus), ("final from a", [])]),
        "tier-b": ScriptLLM([("thinking on b", bogus)]),
    }
    order = ["tier-a", "tier-b", "tier-a"]
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        name = order[calls["n"] - 1]
        return name, states[name]

    box, trace = [], []
    out = run_tool_loop(
        ScriptLLM(["unused"]), "hi", [],
        llm_provider=provider, tier_trace=trace, final_tier=box,
    )
    assert "final from a" in out
    assert trace == ["tier-a", "tier-b"]
    assert box == ["tier-a"]


def test_single_round_records_its_tier():
    box = []
    out = run_tool_loop(
        ScriptLLM(["unused"]), "hi", [],
        llm_provider=lambda: ("solo", ScriptLLM([("done", [])])),
        final_tier=box,
    )
    assert "done" in out
    assert box == ["solo"]


def test_no_provider_leaves_box_for_caller():
    box = []
    out = run_tool_loop(ScriptLLM([("plain", [])]), "hi", [], final_tier=box)
    assert "plain" in out
    assert box == []


def _research_answer(monkeypatch, reflect=None):
    import agent.answer as answer_mod
    import agent.runtime as runtime

    if reflect is not None:
        # Patch where _reflect_with_fallback looks it up.
        monkeypatch.setattr(answer_mod, "reflect_and_improve", reflect)
    states = {
        "tier-a": RaisingLLM([]),
        "tier-b": ScriptLLM([("short reply", [])]),
    }
    order = ["tier-a", "tier-b"]

    def provider():
        name = order.pop(0)
        return name, states[name]

    attempt_llm = ScriptLLM([])
    original_loop = runtime.run_tool_loop

    def _loop_with_provider(llm, user_input, history, *args, **kwargs):
        # Runtime passes its provider positionally (9th after history);
        # swap in the scripted one.
        args = list(args)
        if len(args) > 8:
            args[8] = provider
        else:
            kwargs["llm_provider"] = provider
        return original_loop(llm, user_input, history, *args, **kwargs)

    monkeypatch.setattr(runtime, "run_tool_loop", _loop_with_provider)
    return runtime.answer_with_fallback(
        "search the web for mars",
        deep_mode=True,
        tiers=[("fake", lambda: attempt_llm)],
        raw_messages=[],
    )


def test_reflect_rewrite_attributes_attempt_tier(monkeypatch):
    out = _research_answer(monkeypatch, reflect=lambda *a, **k: "REWRITTEN TEXT")
    assert out["output"] == "REWRITTEN TEXT"
    assert out["active_tier"] == "fake"


def test_unrewritten_draft_keeps_loop_tier(monkeypatch):
    out = _research_answer(monkeypatch, reflect=lambda *a, **k: a[2])
    assert out["output"] == "short reply"
    assert out["active_tier"] == "tier-b"
