"""Fix 4 regression tests: SSE carries real provider tokens.

The stream endpoint used to run the full pipeline, then replay the
finished text word-by-word with sleeps. Now tokens flow live from the
model through TokenStream (with resets when a new call supersedes),
and done/meta keep their contract.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from agent.executor import TokenStream
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def open_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    return tmp_path


@pytest.fixture()
def client(open_env):
    from backend.main import app

    with TestClient(app) as handle:
        yield handle


def _events(res):
    out = []
    for line in res.iter_lines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


def test_token_stream_forward_and_reset():
    calls, resets = [], []
    ts = TokenStream(calls.append, lambda: resets.append(1))
    assert ts.streaming
    ts("a")
    ts("ab")
    assert calls == ["a", "ab"] and resets == []
    ts.reset_for_new_call()
    assert resets == [1]
    ts("c")
    assert calls == ["a", "ab", "c"]
    # Second reset fires again (new emission happened).
    ts.reset_for_new_call()
    assert resets == [1, 1]


def test_token_stream_inert_without_consumer():
    ts = TokenStream()
    assert not ts.streaming
    ts("x")
    ts.reset_for_new_call()


def test_token_stream_swallows_callback_errors():
    def _boom_text(t):
        raise RuntimeError("client gone")

    def _boom_reset():
        raise RuntimeError("client gone")

    ts = TokenStream(_boom_text, _boom_reset)
    ts("x")
    ts.reset_for_new_call()


class FakeStreamLLM:
    """Streams fixed pieces; first stream() may carry tool calls."""

    def __init__(self, rounds):
        # rounds: list of (pieces, tool_calls_or_None), one per stream() call.
        self._rounds = list(rounds)
        self._n = 0

    def bind_tools(self, tools):
        return self

    def stream(self, messages):
        from langchain_core.messages import AIMessageChunk

        pieces, calls = self._rounds[min(self._n, len(self._rounds) - 1)]
        self._n += 1
        for i, p in enumerate(pieces):
            if calls is not None and i == len(pieces) - 1:
                yield AIMessageChunk(content=p, tool_calls=calls)
            else:
                yield AIMessageChunk(content=p)


def test_invoke_bounded_streams_cumulative():
    from agent.executor import _invoke_bounded

    llm = FakeStreamLLM([(["hello ", "world"], None)])
    seen = []
    out = _invoke_bounded(llm, ["hi"], timeout=10.0, on_token=seen.append)
    assert str(out.content) == "hello world"
    assert seen == ["hello ", "hello world"]


def test_invoke_bounded_silent_without_callback():
    from agent.executor import _invoke_bounded

    llm = FakeStreamLLM([(["quiet answer"], None)])
    out = _invoke_bounded(llm, ["hi"], timeout=10.0)
    assert str(out.content) == "quiet answer"


def test_tool_loop_single_round_no_reset():
    from agent.toolrun import run_tool_loop

    llm = FakeStreamLLM([(["final text"], None)])
    seen, resets = [], []
    out = run_tool_loop(llm, "hi", [], on_token=seen.append,
                        on_reset=lambda: resets.append(1))
    assert "final text" in out
    assert seen and seen[-1] == "final text"
    assert resets == []


def test_tool_loop_resets_between_rounds():
    from agent.toolrun import run_tool_loop

    calls = [{"name": "bogus-tool-xyz", "args": {}, "id": "call-1"}]
    llm = FakeStreamLLM([
        (["thinking aloud "], calls),
        (["final answer"], None),
    ])
    seen, resets = [], []
    out = run_tool_loop(llm, "hi", [], on_token=seen.append,
                        on_reset=lambda: resets.append(1))
    assert "final answer" in out
    assert resets == [1]
    assert seen[-1] == "final answer"
    assert any("thinking aloud" in t for t in seen)


def test_stream_forwards_live_tokens_verbatim(client, monkeypatch):
    def _answer(user_input, history=None, **kwargs):
        cb = kwargs.get("on_token")
        assert callable(cb), "agent must receive the token callback"
        cb("partial one ")
        cb("partial one two")
        return {
            "output": "partial one two",
            "active_tier": "Stub",
            "task_type": "simple",
            "warnings": [],
        }

    monkeypatch.setattr(agent, "answer_with_fallback", _answer)
    with client.stream("POST", "/api/chat/stream", json={"content": "hi"}) as res:
        assert res.status_code == 200
        events = _events(res)
    # Verbatim passthrough in order — the old word-splitting replay
    # would have emitted different chunks ("partial", "partial one", ...).
    assert [e["type"] for e in events] == ["token", "token", "meta", "done"]
    assert [e["text"] for e in events if e["type"] == "token"] == ["partial one ", "partial one two"]
    done = events[-1]["result"]
    assert done["message"]["content"] == "partial one two"
    assert done["active_tier"] == "Stub"


def test_stream_forwards_reset(client, monkeypatch):
    def _answer(user_input, history=None, **kwargs):
        kwargs["on_token"]("first try ")
        kwargs["on_reset"]()
        kwargs["on_token"]("second try")
        return {
            "output": "second try",
            "active_tier": "Stub",
            "task_type": "simple",
            "warnings": [],
        }

    monkeypatch.setattr(agent, "answer_with_fallback", _answer)
    with client.stream("POST", "/api/chat/stream", json={"content": "hi"}) as res:
        events = _events(res)
    assert [e["type"] for e in events] == ["token", "reset", "token", "meta", "done"]


def test_stream_error_event(client, monkeypatch):
    def _answer(user_input, history=None, **kwargs):
        raise ValueError("bad input here")

    monkeypatch.setattr(agent, "answer_with_fallback", _answer)
    with client.stream("POST", "/api/chat/stream", json={"content": "hi"}) as res:
        assert res.status_code == 200
        events = _events(res)
    assert [e["type"] for e in events] == ["error"]
    assert events[0]["detail"] == "bad input here"


class FlakyStreamLLM:
    """Streaming double with injectable failures + invoke counting."""

    def __init__(self, pieces, fail_at=None, fail_error=None, setup_error=None):
        from langchain_core.messages import AIMessageChunk

        self._AIMessageChunk = AIMessageChunk
        self._pieces = list(pieces)
        self._fail_at = fail_at
        self._fail_error = fail_error or RuntimeError("mid-stream failure")
        self._setup_error = setup_error
        self.invoke_calls = 0

    def stream(self, messages):
        if self._setup_error is not None:
            raise self._setup_error
        return self._gen()

    def _gen(self):
        for i, p in enumerate(self._pieces):
            if self._fail_at is not None and i == self._fail_at:
                raise self._fail_error
            yield self._AIMessageChunk(content=p)

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        self.invoke_calls += 1
        return AIMessage(content="fallback answer")


def test_midstream_failure_propagates_without_reinvoke():
    from agent.executor import _invoke_bounded

    llm = FlakyStreamLLM(
        ["part one ", "part two"],
        fail_at=1,
        fail_error=RuntimeError("429 quota exceeded mid-stream"),
    )
    seen = []
    with pytest.raises(RuntimeError, match="429 quota exceeded mid-stream"):
        _invoke_bounded(llm, ["hi"], timeout=10.0, on_token=seen.append)
    # No silent full re-invoke on the same tier (double latency/load).
    assert llm.invoke_calls == 0
    # Tokens that arrived before the failure still reached the consumer.
    assert seen == ["part one "]


def test_setup_failure_still_falls_back_to_invoke():
    from agent.executor import _invoke_bounded

    llm = FlakyStreamLLM(["unused"], setup_error=RuntimeError("streaming unsupported"))
    out = _invoke_bounded(llm, ["hi"], timeout=10.0)
    assert str(out.content) == "fallback answer"
    assert llm.invoke_calls == 1


def test_first_chunk_failure_still_falls_back_to_invoke():
    from agent.executor import _invoke_bounded

    llm = FlakyStreamLLM(["unused"], fail_at=0, fail_error=ValueError("bad first chunk"))
    out = _invoke_bounded(llm, ["hi"], timeout=10.0)
    assert str(out.content) == "fallback answer"
    assert llm.invoke_calls == 1


def test_fallback_path_is_logged(caplog):
    import logging

    from agent.executor import _invoke_bounded

    llm = FlakyStreamLLM(["unused"], setup_error=RuntimeError("streaming unsupported"))
    with caplog.at_level(logging.DEBUG, logger="agent.executor"):
        _invoke_bounded(llm, ["hi"], timeout=10.0)
    assert "falling back to invoke" in caplog.text
