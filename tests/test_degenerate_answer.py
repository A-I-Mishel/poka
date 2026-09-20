"""Degenerate answers ("B" persisted as a whole reply) fail over.

A stripped length below 2 characters can never carry an answer — except
numbering-only exam replies ("D", "4"), exempt when shaped like
numbering or when the request asked for numbering/letters only.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.toolrun import is_degenerate_answer


def test_empty_is_degenerate():
    assert is_degenerate_answer("") is True
    assert is_degenerate_answer("   ") is True
    assert is_degenerate_answer(None) is True


def test_single_token_glitch_is_degenerate():
    assert is_degenerate_answer("B", "do you have info on the paper?") is True
    assert is_degenerate_answer("B.", "summarize this") is True
    assert is_degenerate_answer("x", "hello") is True


def test_numbering_answers_exempt():
    assert is_degenerate_answer("D", "only mention the correct numbering") is False
    assert is_degenerate_answer("4", "answer with the letter only") is False
    assert is_degenerate_answer("iv) 4", "solve this") is False
    assert is_degenerate_answer("i) 1 ii) 3", "solve this") is False


def test_short_but_real_answers_untouched():
    for text in ("No.", "Yes", "ok", "hi!", "A+"):
        assert is_degenerate_answer(text, "do you know sam altman?") is False, text


def test_loop_fails_over_on_degenerate(monkeypatch):
    """Tool loop retries the round instead of persisting junk."""
    from agent.toolrun import run_tool_loop

    class ScriptLLM:
        def __init__(self, script):
            self._script = list(script)

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            from types import SimpleNamespace

            item = self._script.pop(0)
            if isinstance(item, Exception):
                raise item
            text, calls = item if isinstance(item, tuple) else (item, [])
            return SimpleNamespace(content=text, tool_calls=calls)

    order = []

    def provider():
        return order.pop(0)

    bad = ScriptLLM(["B"])
    good = ScriptLLM(["Proper answer here."])
    order += [("bad", bad), ("good", good)]
    out = run_tool_loop(
        bad, "summarize the report", [], max_rounds=2,
        llm_provider=provider)
    assert out == "Proper answer here."


def test_loop_single_tier_degenerate_message():
    """Without failover tiers, junk becomes an honest failure message."""
    from agent.toolrun import run_tool_loop

    class ScriptLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            from types import SimpleNamespace

            return SimpleNamespace(content="B", tool_calls=[])

    out = run_tool_loop(ScriptLLM(), "summarize the report", [], max_rounds=2)
    assert out == "I couldn't generate a response. Please try again."


def test_simple_path_fails_over_on_degenerate(monkeypatch):
    """Simple answers route to the next tier instead of storing 'B'."""
    import agent as agent_mod
    from agent import runtime as rt_mod
    from types import SimpleNamespace

    calls = []

    def _invoke(llm, messages, budget=None, **kw):
        calls.append(1)
        if len(calls) == 1:
            return SimpleNamespace(content="B")
        return SimpleNamespace(content="A fuller answer.")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    res = rt_mod.answer_with_fallback(
        "do you know sam altman?",
        tiers=[("A", lambda: object()), ("B", lambda: object())])
    assert res["output"] == "A fuller answer."
    assert res["active_tier"] == "B"
    assert len(calls) == 2


def test_past_upload_none_clarifies():
    from agent.attachment_gate import decide

    d = decide("do you have any information on the paper i uploaded?", [], [])
    assert d["use_images"] == [] and d["use_docs"] == []
    assert d["clarify"] is not None
    assert "stay with the chat" in d["clarify"]
