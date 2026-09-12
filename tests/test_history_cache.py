"""History-shaping tests: one owner, cached summaries.

chatflow passes raw history; runtime summarizes long histories once
and reuses the cached shaping while the conversation is unchanged.
Same-count edits must recompute (count alone would serve stale text).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent.runtime as runtime
from services import context as ctx


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("cache-user")
    agent._clear_summary_cache()
    yield
    ctx.set_current_user_id(None)
    agent._clear_summary_cache()


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def invoke(self, messages):
        from types import SimpleNamespace

        self.calls.append(messages)
        return SimpleNamespace(content=self.script.pop(0), tool_calls=[])


def _history(n=8):
    out = []
    for i in range(n):
        out.append({"role": "user", "content": "question %d" % i})
        out.append({"role": "assistant", "content": "answer %d" % i})
    return out


def _answer(history, fake):
    return agent.answer_with_fallback(
        "hello", tiers=[("fake", lambda: fake)], raw_messages=history
    )


def test_long_history_summarized_once():
    history = _history(8)
    fake = FakeLLM(["the summary", "answer one", "answer one"])
    out1 = _answer(history, fake)
    assert out1["output"] == "answer one"
    assert len(fake.calls) == 2
    out2 = _answer(history, fake)
    assert out2["output"] == "answer one"
    assert len(fake.calls) == 3


def test_edited_history_recomputes():
    history = _history(8)
    fake = FakeLLM(["sum v1", "answer one", "sum v2", "answer one"])
    _answer(history, fake)
    assert len(fake.calls) == 2
    history[3] = {"role": "assistant", "content": "edited answer"}
    _answer(history, fake)
    assert len(fake.calls) == 4


def test_short_history_never_summarizes():
    fake = FakeLLM(["answer one"])
    out = _answer(_history(2), fake)
    assert out["output"] == "answer one"
    assert len(fake.calls) == 1


def test_cache_is_per_user():
    history = _history(8)
    fake = FakeLLM(["sum a", "answer one", "sum b", "answer one"])
    _answer(history, fake)
    assert len(fake.calls) == 2
    ctx.set_current_user_id("other-user")
    _answer(history, fake)
    assert len(fake.calls) == 4


def test_cache_bounded(monkeypatch):
    monkeypatch.setattr(runtime, "_SUMMARY_CACHE_MAX", 3)
    for i in range(5):
        history = _history(8)
        history[0] = {"role": "user", "content": "unique %d" % i}
        fake = FakeLLM(["sum", "answer one"])
        _answer(history, fake)
    assert len(runtime._SUMMARY_CACHE) <= 3
