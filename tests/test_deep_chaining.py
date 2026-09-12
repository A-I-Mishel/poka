"""Deep-mode chaining: loops run past 4 rounds inside raised budgets.

Normal mode keeps the historical cap of 4 rounds + final synthesis.
The shared round budget (not just the per-loop cap) bounds nested
loops, and exhaustion synthesizes instead of erroring.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from agent.budget import BudgetExhausted, RequestBudget
from agent.toolrun import run_tool_loop
from services import context as ctx


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("chain-user")
    agent._clear_summary_cache()
    yield
    ctx.set_current_user_id(None)


class ScriptLLM:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        from types import SimpleNamespace

        self.calls.append(messages)
        item = self._script.pop(0) if self._script else "ok"
        text, calls = item if isinstance(item, tuple) else (item, [])
        return SimpleNamespace(content=text, tool_calls=calls)


BOGUS = [{"name": "bogus-tool-xyz", "args": {}, "id": "1"}]


def test_budget_count_round_default_cap():
    b = RequestBudget()
    for _ in range(4):
        b.count_round()
    with pytest.raises(BudgetExhausted):
        b.count_round()


def test_budget_count_round_custom_cap():
    b = RequestBudget(max_rounds=12)
    for _ in range(12):
        b.count_round()
    with pytest.raises(BudgetExhausted):
        b.count_round()


def test_loop_budget_exhaustion_synthesizes():
    llm = ScriptLLM([("thinking", BOGUS), ("synthesis done", [])])
    out = run_tool_loop(
        llm, "hi", [], max_rounds=10, budget=RequestBudget(max_rounds=1)
    )
    assert out == "synthesis done"
    assert len(llm.calls) == 2


def test_deep_mode_chains_past_four():
    script = [("thinking %d" % i, BOGUS) for i in range(6)]
    script.append("final answer " + "x" * 80)
    llm = ScriptLLM(script)
    # One tier entry per round: the runtime failover provider serves
    # each round from the next unattempted tier.
    tiers = [("f%d" % i, lambda: llm) for i in range(7)]
    out = agent.answer_with_fallback(
        "search the web for mars",
        deep_mode=True,
        tiers=tiers,
        raw_messages=[],
    )
    assert "final answer" in out["output"]
    assert len(llm.calls) == 7


def test_fast_mode_still_stops_at_four():
    script = [("thinking %d" % i, BOGUS) for i in range(4)]
    script.append("synth done")
    llm = ScriptLLM(script)
    tiers = [("f%d" % i, lambda: llm) for i in range(5)]
    out = agent.answer_with_fallback(
        "search the web for mars",
        tiers=tiers,
        raw_messages=[],
    )
    assert out["output"] == "synth done"
    assert len(llm.calls) == 5


def test_single_tier_chains_multiple_rounds():
    """One healthy tier must serve every round (provider reuses it)."""
    script = [("thinking %d" % i, BOGUS) for i in range(3)]
    script.append("final answer here")
    llm = ScriptLLM(script)
    out = agent.answer_with_fallback(
        "search the web for mars",
        tiers=[("only", lambda: llm)],
        raw_messages=[],
    )
    assert out["output"] == "final answer here"
    assert len(llm.calls) == 4


def test_unconfigured_tier_skipped_not_fatal():
    """A None-returning tier is skipped; healthy tiers keep chaining."""
    script = [("thinking %d" % i, BOGUS) for i in range(2)]
    script.append("final answer here")
    llm = ScriptLLM(script)
    tiers = [("ghost", lambda: None), ("real", lambda: llm)]
    out = agent.answer_with_fallback(
        "search the web for mars",
        tiers=tiers,
        raw_messages=[],
    )
    assert out["output"] == "final answer here"
    assert len(llm.calls) == 3
