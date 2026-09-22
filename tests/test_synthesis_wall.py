"""Deep-wall synthesis scaling: no quota burned on doomed attempts (no network).

When the request wall is nearly spent, final synthesis is skipped
straight to salvage; otherwise each attempt's timeout shrinks to fit
the remaining wall. Unit-tested via stubbed invoke boundaries.
"""

import os
import sys
import time
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from agent.budget import RequestBudget, remaining_seconds
from agent import toolrun as tr


def test_remaining_seconds():
    assert remaining_seconds(None) == float("inf")
    fresh = RequestBudget()
    assert remaining_seconds(fresh) > 200
    spent = RequestBudget(deadline=time.monotonic() - 1.0)
    assert remaining_seconds(spent) <= 0
    wall = RequestBudget(deadline=time.time() + 60.0)
    assert 0 < remaining_seconds(wall) <= 60.0
    assert remaining_seconds(object()) == float("inf")


def test_synthesis_timeout_scaling():
    assert tr._synthesis_timeout_for_wall(None) == 60.0
    assert tr._synthesis_timeout_for_wall(RequestBudget()) == 60.0
    # Wall-clock math: allow sub-second scheduling jitter.
    assert tr._synthesis_timeout_for_wall(
        RequestBudget(deadline=time.monotonic() + 25.0)) == pytest.approx(20.0, abs=1.0)
    assert tr._synthesis_timeout_for_wall(
        RequestBudget(deadline=time.monotonic() + 16.0)) == pytest.approx(11.0, abs=1.0)
    assert tr._synthesis_timeout_for_wall(
        RequestBudget(deadline=time.monotonic() + 12.0)) is None
    assert tr._synthesis_timeout_for_wall(
        RequestBudget(deadline=time.monotonic() - 5.0)) is None


class _ScriptLLM:
    def __init__(self, script):
        self._script = list(script)
        self.invokes = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.invokes += 1
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        text, calls = item if isinstance(item, tuple) else (item, [])
        return types.SimpleNamespace(content=text, tool_calls=calls)


def _big_results(monkeypatch):
    monkeypatch.setattr(
        tr, "_execute_tool_calls_parallel",
        lambda tcs, budget: ["R TOOL RESULT"])


def test_spent_wall_skips_synthesis_to_salvage(monkeypatch):
    _big_results(monkeypatch)
    llm = _ScriptLLM([("", [{"name": "web_search", "args": {"query": "q"}}])])
    budget = RequestBudget(deadline=time.monotonic() + 5.0)
    out = tr.run_tool_loop(llm, "search things", [], max_rounds=1, budget=budget)
    # One round ran; synthesis skipped (wall < minimum) -> tool salvage.
    assert llm.invokes == 1
    assert "tool results that did come back" in out


def test_retry_loop_stops_at_spent_wall(monkeypatch):
    _big_results(monkeypatch)
    llm = _ScriptLLM([("", [{"name": "web_search", "args": {"query": "q"}}]),
                      RuntimeError("tier died mid-synthesis")])
    provider_calls = []

    def _provider():
        provider_calls.append(1)
        return ("t2", llm)

    budget = RequestBudget(deadline=time.monotonic() + 5.0)
    out = tr.run_tool_loop(llm, "search things", [], max_rounds=1,
                           budget=budget, llm_provider=_provider)
    # One provider pull (the tool round); the failed synthesis never
    # pulls a second tier (zero extra quota burned on a spent wall).
    assert len(provider_calls) == 1
    assert "tool results that did come back" in out


def test_synthesis_timeout_scaled_to_wall(monkeypatch):
    _big_results(monkeypatch)
    seen = {}

    def _invoke(llm, messages, budget=None, **kw):
        seen.setdefault("timeouts", []).append(kw.get("timeout"))
        return llm.invoke(messages)

    monkeypatch.setattr(agent, "_invoke_bounded", _invoke)
    llm = _ScriptLLM([("", [{"name": "web_search", "args": {"query": "q"}}]),
                      "final answer"])
    budget = RequestBudget(deadline=time.monotonic() + 25.0)
    out = tr.run_tool_loop(llm, "search things", [], max_rounds=1, budget=budget)
    assert out == "final answer"
    # Round invoke carries no timeout kwarg; synthesis is wall-scaled
    # (approx: live wall-clock jitter).
    assert seen["timeouts"][-1] == pytest.approx(20.0, abs=1.0)


def test_synthesis_timeout_full_on_fresh_wall(monkeypatch):
    _big_results(monkeypatch)
    seen = {}

    def _invoke(llm, messages, budget=None, **kw):
        seen.setdefault("timeouts", []).append(kw.get("timeout"))
        return llm.invoke(messages)

    monkeypatch.setattr(agent, "_invoke_bounded", _invoke)
    llm = _ScriptLLM([("", [{"name": "web_search", "args": {"query": "q"}}]),
                      "final answer"])
    out = tr.run_tool_loop(llm, "search things", [], max_rounds=1,
                           budget=RequestBudget())
    assert out == "final answer"
    assert seen["timeouts"][-1] == 60.0
