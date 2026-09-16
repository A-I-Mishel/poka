"""Reflection pass tests: marker anchorship, rewrite quality guard, bounded draft.

Agent._invoke_bounded is stubbed (no network, no quota); reflects only
the pure decision/marker logic and the safe-default contract.
"""

import os
import sys
import types


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from agent.reflection import (
    _has_improve_marker,
    _improved_text,
    _strip_fences,
    reflect_and_improve,
    should_reflect,
)
from services.limits import REFLECT_SHORT_DRAFT_CHARS


def _fake_reply(text):
    def fake(llm, msgs, **kw):
        return types.SimpleNamespace(content=text)

    return fake


def test_strip_fences():
    assert _strip_fences("```text\nhello\n```").startswith("hello")
    assert _strip_fences("plain") == "plain"


def test_improve_marker_matches_line_start_only():
    assert _has_improve_marker("[IMPROVE] better") is True
    assert _has_improve_marker("[improve] better") is True
    assert _has_improve_marker("You should reply: [IMPROVE] better") is False
    assert _has_improve_marker("[PASS]") is False
    assert _has_improve_marker("") is False


def test_improved_text_extracts_after_marker():
    assert _improved_text("[IMPROVE] new version here") == "new version here"


def test_reflect_returns_rewrite_when_long_enough(monkeypatch):
    monkeypatch.setattr(
        agent, "_invoke_bounded",
        _fake_reply("[IMPROVE] A much better, longer and complete rewrite."))
    out = reflect_and_improve(None, "q", "short draft here", [])
    assert out.startswith("A much better")


def test_reflect_keeps_draft_for_lossy_short_rewrite(monkeypatch):
    draft = "A long draft answer that covers every single point in detail and then some."
    monkeypatch.setattr(agent, "_invoke_bounded", _fake_reply("[IMPROVE] shorter"))
    out = reflect_and_improve(None, "q", draft, [])
    assert out == draft


def test_reflect_ignores_instruction_echo(monkeypatch):
    draft = "A sufficiently long draft that is complete and correct for the user."
    echo = "If it needs improvement, reply with: [IMPROVE] followed by the full version."
    monkeypatch.setattr(agent, "_invoke_bounded", _fake_reply(echo))
    out = reflect_and_improve(None, "q", draft, [])
    assert out == draft


def test_reflect_failure_keeps_draft(monkeypatch):
    def boom(llm, msgs, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(agent, "_invoke_bounded", boom)
    draft = "A perfectly good draft that should survive any critique failure."
    assert reflect_and_improve(None, "q", draft, []) == draft


def test_should_reflect_short_draft_threshold_matches_limits():
    assert should_reflect("research", "x" * (REFLECT_SHORT_DRAFT_CHARS - 1), "", deep_mode=True) is True
    assert should_reflect("research", "y" * (REFLECT_SHORT_DRAFT_CHARS + 1), "", deep_mode=True) is False


def test_should_reflect_failure_keyword_and_modes():
    assert should_reflect("research", "the model failed to find anything here", "", deep_mode=True) is True
    assert should_reflect("research", "fine answer here", "", deep_mode=False) is False
    assert should_reflect("simple", "anything at all", "", deep_mode=True) is False


def _capture_reply(monkeypatch, text="[PASS]"):
    """Stub _invoke_bounded, capturing the prompt; returns the prompt box."""
    box = {}

    def fake(llm, msgs, **kw):
        box["prompt"] = str(msgs[-1].content)
        box["kw"] = kw
        return types.SimpleNamespace(content=text)

    monkeypatch.setattr(agent, "_invoke_bounded", fake)
    return box


def test_reflect_prompt_carries_task_focus(monkeypatch):
    box = _capture_reply(monkeypatch)
    reflect_and_improve(None, "q", "a decent draft answer here", [], task_type="research")
    assert "training knowledge" in box["prompt"]
    box = _capture_reply(monkeypatch)
    reflect_and_improve(None, "q", "a decent draft answer here", [], task_type="data")
    assert "edge cases" in box["prompt"]


def test_reflect_prompt_defaults_focus_for_unknown_task(monkeypatch):
    box = _capture_reply(monkeypatch)
    reflect_and_improve(None, "q", "a decent draft answer here", [])
    assert "accurate, complete, well-structured" in box["prompt"]


def test_reflect_prompt_has_severity_rule(monkeypatch):
    box = _capture_reply(monkeypatch)
    reflect_and_improve(None, "q", "a decent draft answer here", [], task_type="creative")
    assert "ONLY when" in box["prompt"]
    assert "wrong, missing, or unsafe" in box["prompt"]
