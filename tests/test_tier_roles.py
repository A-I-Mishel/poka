"""Role-based tier tables: synthesis/cheap/fallback routing (Milestone 2a).

Prod-default calls (tiers=None) split dumb calls (classify, summarize,
planning, reflection) onto cheap tiers and final answers onto the
synthesis table; caller-supplied tables keep legacy behavior exactly.
"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent.runtime as runtime
from agent.planning import plan_then_execute
from services import context as ctx


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("role-user")
    ctx.set_limit_key("role-user")
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
    agent._clear_summary_cache()
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)


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


def test_role_tables_shape():
    from config import CHEAP_TIERS, SYNTHESIS_TIERS, TIER_GETTERS

    synth_names = [n for n, _ in SYNTHESIS_TIERS]
    assert synth_names[:3] == ["Groq", "Gemini 3.6 Flash", "Gemini 3.5 Flash"]
    assert "NVIDIA" not in synth_names
    assert set(synth_names) | {"NVIDIA"} == {n for n, _ in TIER_GETTERS}
    assert [n for n, _ in CHEAP_TIERS] == [
        "Groq", "GitHub Models", "NVIDIA", "Mistral"]


def test_groq_first_gemini_escalates():
    # Groq leads synthesis; a dead Groq fails over to Gemini 3.6
    # (escalation), proving the reorder keeps Gemini reachable.
    from config import SYNTHESIS_TIERS

    assert [n for n, _ in SYNTHESIS_TIERS][:2] == ["Groq", "Gemini 3.6 Flash"]

    def _dead_groq():
        raise RuntimeError("Groq 429 rate limited")

    gemini = FakeLLM(["gemini answered"])
    out = agent.answer_with_fallback(
        "hello there friend",
        tiers=[("Groq", _dead_groq), ("Gemini 3.6 Flash", lambda: gemini)],
        raw_messages=[])
    assert out["output"] == "gemini answered"
    assert out["active_tier"] == "Gemini 3.6 Flash"


def test_classify_uses_cheap_table(monkeypatch):
    cheap = FakeLLM(["research"])
    synth = FakeLLM(["final answer"])
    monkeypatch.setattr(runtime, "CHEAP_TIERS", [("cheap", lambda: cheap)])
    monkeypatch.setattr(runtime, "SYNTHESIS_TIERS", [("s", lambda: synth)])
    out = agent.answer_with_fallback(
        "flibbertigibbet blorpt doodle snooze wibble wobble extra words here",
        raw_messages=[],
    )
    assert out["task_type"] == "research"
    assert out["active_tier"] == "s"
    assert out["output"] == "final answer"
    assert len(cheap.calls) == 1  # classification burned cheap, not synthesis


def test_kill_switch_skips_classifier(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("classifier must not run")

    monkeypatch.setattr(runtime, "classify_task", _boom)
    fake = FakeLLM(["short answer"])
    out = agent.answer_with_fallback(
        "flib?", tiers=[("fake", lambda: fake)], raw_messages=[])
    assert out["task_type"] == "simple"
    assert out["output"] == "short answer"
    assert out["tools_used"] == []


def test_attachment_hints_bypass_kill_switch(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("classifier must not run")

    monkeypatch.setattr(runtime, "classify_task", _boom)
    fake = FakeLLM(["ack"])
    hinted = ("Next\n\n[Attached document 'd' with upload ID: "
              "abcdef1234567890. To read it, call read_document.]")
    out = agent.answer_with_fallback(
        hinted, tiers=[("fake", lambda: fake)], raw_messages=[])
    # Upload-ID hints prove tool relevance: research, never direct-simple.
    assert out["task_type"] == "research"
    assert out["output"] == "ack"


def test_synthesis_fallback_marks_degraded(monkeypatch):
    def _dead():
        raise RuntimeError("synthesis down")

    monkeypatch.setattr(runtime, "SYNTHESIS_TIERS", [("dead", _dead)])
    fallback = FakeLLM(["fallback answer"])
    monkeypatch.setattr(agent, "TIER_AGENT_GETTERS",
                        [("fb", lambda: fallback)])
    out = agent.answer_with_fallback("hello there friend", raw_messages=[])
    assert out["output"] == "fallback answer"
    assert out["fallback"] == {"requested": "synthesis",
                               "reason": "synthesis tiers unavailable"}


def test_midloop_quota_guard_no_hammer():
    from agent.cascade import _record_tier_failure

    calls = []

    def _getter():
        calls.append(1)
        return FakeLLM([("", [{"name": "check_logic", "args": {
            "operation": "valid", "premises": "p -> q\np",
            "conclusion": "q"}, "id": "1"}])])

    def _cool_after_first_round(_text):
        # Simulate the whole table hitting quota mid-turn: round 2 must
        # fail fast instead of re-hammering the cooled table every round.
        _record_tier_failure("solo", "rate_limit", Exception("429 quota exceeded"))

    out = agent.answer_with_fallback(
        "search the latest logic news", tiers=[("solo", _getter)],
        raw_messages=[], on_progress=_cool_after_first_round)
    assert calls == [1]
    assert isinstance(out["output"], str)


def test_config_has_no_dead_asserts():
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "config.py").read_text(encoding="utf-8")
    assert "assert key is not None" not in src


def test_custom_table_single_pass_no_fallback():
    attempts = []

    def _dead():
        attempts.append(1)
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        agent.answer_with_fallback("hello there friend",
                                   tiers=[("dead", _dead)], raw_messages=[])
    assert attempts == [1]


def test_cheap_planning_first(monkeypatch):
    from agent.budget import RequestBudget

    cheap = FakeLLM(["1. do the thing"])
    attempt = FakeLLM([("done", [])])
    out = plan_then_execute(
        attempt, "do thing", [], budget=RequestBudget(),
        cheap_tiers=[("c", lambda: cheap)])
    assert out == "done"
    assert len(cheap.calls) == 1
    assert len(attempt.calls) == 1  # execution only; plan came from cheap


def test_cheap_planning_falls_back_to_attempt(monkeypatch):
    from agent.budget import RequestBudget

    def _dead():
        raise RuntimeError("cheap down")

    attempt = FakeLLM(["plan by attempt", ("done", [])])
    out = plan_then_execute(
        attempt, "do thing", [], budget=RequestBudget(),
        cheap_tiers=[("dead", _dead)])
    assert out == "done"
    assert len(attempt.calls) == 2  # plan + execution on the attempt tier


def test_cheap_reflection_attributes_rewriter():
    improved = ("[IMPROVE] rewritten draft text that is long enough "
                "to pass the improvement ratio gate easily")
    cheap = FakeLLM([improved])
    text, writer = runtime._reflect_with_fallback(
        FakeLLM(["unused"]), "q", "a short draft here", [], None,
        "research", "attempt", cheap_tiers=[("c", lambda: cheap)])
    assert text.startswith("rewritten draft")
    assert writer == "c"


def test_reflection_legacy_path_unchanged():
    improved = ("[IMPROVE] rewritten draft text that is long enough "
                "to pass the improvement ratio gate easily")
    attempt = FakeLLM([improved])
    text, writer = runtime._reflect_with_fallback(
        attempt, "q", "a short draft here", [], None,
        "research", "attempt", cheap_tiers=None)
    assert text.startswith("rewritten draft")
    assert writer == "attempt"
