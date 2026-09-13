"""Mid-task continuation: a dying tier never restarts the turn.

If the working model fails mid-turn, the next live tier continues the
SAME turn: planning failure cools the attempt tier and execution
proceeds on the next tier; synthesis failure fails over before falling
back to a salvaged partial answer. Collected tool results are kept.
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
    agent._clear_summary_cache()
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()


class ScriptLLM:
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


class CountingRaisingLLM(ScriptLLM):
    """Counts invocations, then always fails."""

    def __init__(self):
        super().__init__([])
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        raise RuntimeError("tier is down")


class FlakyLLM(ScriptLLM):
    """Pops script items; Exception items are raised when reached."""

    def invoke(self, messages):
        from types import SimpleNamespace

        item = self._script.pop(0) if self._script else "ok"
        if isinstance(item, Exception):
            raise item
        text, calls = item if isinstance(item, tuple) else (item, [])
        return SimpleNamespace(content=text, tool_calls=calls)


BOGUS = [{"name": "bogus-tool-xyz", "args": {}, "id": "1"}]


def test_planning_failure_continues_on_next_tier():
    """Dead planning tier is skipped; execution finishes on next tier.

    The dead tier is hit exactly once (the planning call) — execution
    continues directly on the next live tier instead of retrying dead
    or restarting the turn.
    """
    dead = CountingRaisingLLM()
    alive = ScriptLLM(["finished by alive"])
    out = agent.answer_with_fallback(
        "write a presentation about mars",  # rule-routes to creative
        deep_mode=True,  # creative + deep => planning path
        tiers=[("dead", lambda: dead), ("alive", lambda: alive)],
        raw_messages=[],
    )
    assert out["output"] == "finished by alive"
    assert out["active_tier"] == "alive"
    # Exactly 2 hits on dead: the planning call, plus the best-effort
    # reflection probe (which safely keeps the draft on failure).
    # Execution itself never touched dead again — no retry, no restart.
    assert dead.calls == 2


def test_synthesis_failure_continues_on_next_tier():
    """Dead synthesis tier fails over instead of salvaging partial."""
    flaky = FlakyLLM([("thinking", BOGUS), RuntimeError("synthesis down")])
    backup = ScriptLLM(["backup synthesis"])
    order = [("flaky", flaky), ("backup", backup)]

    def provider():
        if not order:
            raise RuntimeError("no live tier")
        return order.pop(0)

    box = []
    out = run_tool_loop(
        flaky, "hi", [], max_rounds=1, llm_provider=provider, final_tier=box
    )
    assert out == "backup synthesis"
    assert box == ["backup"]
