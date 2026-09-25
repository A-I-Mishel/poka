"""Mode-based answer tiers: fast mode uses FAST_TIERS only, deep uses all.

Fast = Gemini 3.1 Flash Lite -> Nemotron Ultra -> Ling VL (Ollama 8B
is deep-only offline tail: fast answers must never come from the
weakest lane). All-fast-down fails honestly (no full-cascade
escape hatch); deep mode keeps today's behavior exactly (full
SYNTHESIS_TIERS + escape hatch, Ollama 8B at the tail as well).
"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent.runtime as runtime
from services import context as ctx


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("fast-user")
    ctx.set_limit_key("fast-user")
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
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

    def invoke(self, messages):
        self.calls.append(messages)
        if not self.script:
            return SimpleNamespace(content="default answer")
        return SimpleNamespace(content=self.script.pop(0))


def _cheap_simple(monkeypatch):
    """Force the simple path: classifier answers 'simple' on cheap."""
    cheap = FakeLLM(["simple"])
    monkeypatch.setattr(runtime, "CHEAP_TIERS", [("cheap", lambda: cheap)])
    return cheap


def test_fast_tiers_shape():
    from config import FAST_TIERS, SYNTHESIS_TIERS

    names = [n for n, _ in FAST_TIERS]
    assert names == ["Gemini 3.1 Flash Lite", "OpenRouter Nemotron Ultra",
                      "OpenRouter Ling VL"]
    assert "Ollama 8B" not in names  # deep-only offline tail
    assert set(names) < {n for n, _ in SYNTHESIS_TIERS}


def test_fast_mode_tries_only_fast_tiers_in_order(monkeypatch):
    seen = []

    def _dead():
        seen.append("dead")
        raise RuntimeError("fast lane down")

    good = FakeLLM(["fast answer"])
    monkeypatch.setattr(runtime, "FAST_TIERS",
                        [("fast-dead", _dead), ("fast-good", lambda: good)])
    monkeypatch.setattr(runtime, "SYNTHESIS_TIERS",
                        [("s", lambda: (_ for _ in ()).throw(
                            AssertionError("synthesis must not run in fast mode")))])
    _cheap_simple(monkeypatch)
    out = agent.answer_with_fallback("flib?", raw_messages=[], deep_mode=False)
    assert out["output"] == "fast answer"
    assert out["active_tier"] == "fast-good"
    assert seen == ["dead"]  # order kept, dead lane failed over


def test_fast_mode_all_down_fails_honestly(monkeypatch):
    def _dead():
        raise RuntimeError("fast lane down")

    def _boom():
        raise AssertionError("escape hatch must not run in fast mode")

    monkeypatch.setattr(runtime, "FAST_TIERS", [("d1", _dead), ("d2", _dead)])
    monkeypatch.setattr(agent, "TIER_AGENT_GETTERS", [("fb", _boom)])
    _cheap_simple(monkeypatch)
    with pytest.raises(RuntimeError):
        agent.answer_with_fallback("flib?", raw_messages=[], deep_mode=False)


def test_deep_mode_uses_full_synthesis_table(monkeypatch):
    seen = []

    def _dead():
        seen.append("dead")
        raise RuntimeError("synth lane down")

    good = FakeLLM(["deep answer"])
    monkeypatch.setattr(runtime, "SYNTHESIS_TIERS",
                        [("s-dead", _dead), ("s-good", lambda: good)])
    monkeypatch.setattr(runtime, "FAST_TIERS",
                        [("f", lambda: (_ for _ in ()).throw(
                            AssertionError("fast table must not run in deep mode")))])
    _cheap_simple(monkeypatch)
    out = agent.answer_with_fallback("flib?", raw_messages=[], deep_mode=True)
    assert out["output"] == "deep answer"
    assert out["active_tier"] == "s-good"
    assert seen == ["dead"]
