"""Phase 4 tests: tier-aware prompts, planning validation, fast reflection,
citation verification, episodic summaries. All stubbed (no quota)."""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent.runtime as runtime
from agent.planning import _unknown_plan_tools, plan_then_execute
from agent.reflection import should_reflect
from services import context as ctx


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("p4-user")
    ctx.set_limit_key("p4-user")
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


# --- tier-aware prompts ------------------------------------------


def test_strict_tier_set():
    from agent.prompts import STRICT_GROUNDING_PARAGRAPH, is_strict_tier

    assert is_strict_tier("NVIDIA") is True
    assert is_strict_tier("Mistral") is True
    assert is_strict_tier("Gemini 3.6 Flash") is False
    assert is_strict_tier(None) is False
    assert "ONLY from the tool results" in STRICT_GROUNDING_PARAGRAPH


def test_simple_answer_strict_only_for_weak_tiers():
    weak = FakeLLM(["weak answer text here"])
    out = agent.answer_with_fallback(
        "hello there friend", tiers=[("NVIDIA", lambda: weak)], raw_messages=[])
    assert out["output"] == "weak answer text here"
    assert "ONLY from the tool results" in str(weak.calls[0][0].content)

    strong = FakeLLM(["strong answer"])
    agent.answer_with_fallback(
        "hello there friend", tiers=[("Gemini 3.6 Flash", lambda: strong)],
        raw_messages=[])
    assert "ONLY from the tool results" not in str(strong.calls[0][0].content)


# --- planning validation -----------------------------------------


def test_unknown_plan_tools():
    assert _unknown_plan_tools("1. use fetch_web to search") == ["fetch_web"]
    assert _unknown_plan_tools("run `blorp_query` then read") == ["blorp_query"]
    assert _unknown_plan_tools("use the upload_id from step 1") == []
    assert _unknown_plan_tools("1. call read_document 2. call analyze_csv") == []
    assert _unknown_plan_tools("just think step by step") == []


def test_plan_replans_once_then_proceeds():
    from agent.budget import RequestBudget

    cheap = FakeLLM(["1. use fetch_web to search", "1. use web_search to search"])
    attempt = FakeLLM([("done", [])])
    out = plan_then_execute(
        attempt, "search things", [], budget=RequestBudget(),
        cheap_tiers=[("c", lambda: cheap)])
    assert out == "done"
    assert len(cheap.calls) == 2  # bad plan + one bounded replan
    assert any("Correction" in str(c[-1].content) for c in [cheap.calls[1]])


def test_plan_prompt_has_scaffold():
    from agent.budget import RequestBudget

    cheap = FakeLLM(["1. use web_search"])
    attempt = FakeLLM([("done", [])])
    plan_then_execute(attempt, "q", [], budget=RequestBudget(),
                      cheap_tiers=[("c", lambda: cheap)])
    prompt = str(cheap.calls[0][-1].content)
    assert "Goal:" in prompt and "Expected output:" in prompt


# --- fast reflection ---------------------------------------------


def test_should_reflect_fast_gate():
    assert should_reflect("creative", "x" * 400, "", deep_mode=False) is True
    assert should_reflect("research", "x" * 400, "", deep_mode=False) is True
    assert should_reflect("research", "short", "", deep_mode=False) is False
    assert should_reflect("simple", "x" * 400, "", deep_mode=False) is False
    assert should_reflect("data", "x" * 400, "", deep_mode=False) is False


def test_fast_reflection_improves_creative():
    improved = ("[IMPROVE] " + "rewritten creative draft with plenty of substance "
                "to clear every length gate comfortably. " * 10)
    attempt = FakeLLM([("a long creative draft " * 20, []), (improved, [])])
    out = agent.answer_with_fallback(
        "write an essay about rivers", tiers=[("fake", lambda: attempt)],
        raw_messages=[])
    assert out["output"].startswith("rewritten creative draft")


# --- citation verification ---------------------------------------


def test_unknown_urls_detection():
    sources = [{"url": "https://example.com/page", "title": "Example"}]
    assert runtime._unknown_cited_urls(
        "see https://example.com/page for more", sources) == []
    assert runtime._unknown_cited_urls(
        "see https://evil.example/x", sources) == ["https://evil.example/x"]
    assert runtime._unknown_cited_urls("no links here", sources) == []
    assert runtime._unknown_cited_urls("see https://x.example/", []) == []


def test_verify_skips_without_unknown_urls(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_invoke_bounded",
                        lambda *a, **k: calls.append(1))
    out = runtime._verify_citations(
        "plain answer", [], None, cheap_tiers=[("c", lambda: None)])
    assert out == "plain answer" and calls == []


def test_verify_flags_unretrieved_links(monkeypatch):
    import types

    def fake(llm, messages, **kw):
        return types.SimpleNamespace(content="UNGROUNDED: leans on the blog")

    monkeypatch.setattr(agent, "_invoke_bounded", fake)
    out = runtime._verify_citations(
        "see https://blog.example/post",
        [{"url": "https://example.com/page", "title": "Example"}],
        None, cheap_tiers=[("c", lambda: object())])
    assert "open them critically" in out
    assert "leans on the blog" not in out  # fixed note, never verifier prose


def test_verify_ok_and_failure_keep_draft(monkeypatch):
    import types

    monkeypatch.setattr(
        agent, "_invoke_bounded",
        lambda *a, **k: types.SimpleNamespace(content="OK"))
    out = runtime._verify_citations(
        "see https://blog.example/post",
        [{"url": "https://example.com/page", "title": "Example"}],
        None, cheap_tiers=[("c", lambda: object())])
    assert out == "see https://blog.example/post"

    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(agent, "_invoke_bounded", _boom)
    assert runtime._verify_citations(
        "see https://blog.example/post",
        [{"url": "https://example.com/page", "title": "Example"}],
        None, cheap_tiers=[("c", lambda: object())]
    ) == "see https://blog.example/post"


# --- episodic summaries ------------------------------------------


def _long_history(n=14):
    return [{"role": ("user" if i % 2 == 0 else "assistant"),
             "content": f"message number {i} about graphs"}
            for i in range(n)]


def test_episodic_skips_short_chats(monkeypatch):
    import agent as agent_mod
    from backend.chatflow import maybe_attach_episodic_summary

    calls = []
    monkeypatch.setattr(agent_mod, "_invoke_bounded", lambda *a, **k: calls.append(1))
    record = {"id": "c1", "messages": _long_history(4)}
    assert maybe_attach_episodic_summary(record) == record
    assert calls == [] and "summary" not in record


def test_episodic_attaches_and_caps(monkeypatch):
    import types

    import agent as agent_mod
    import config
    from backend.chatflow import maybe_attach_episodic_summary

    monkeypatch.setattr(
        agent_mod, "_invoke_bounded",
        lambda *a, **k: types.SimpleNamespace(content="S " * 2000))
    monkeypatch.setattr(config, "CHEAP_TIERS", [("c", lambda: object())])
    record = {"id": "c1", "messages": _long_history(16)}
    out = maybe_attach_episodic_summary(record)
    assert 0 < len(out["summary"]) <= 2000


def test_episodic_failure_keeps_record(monkeypatch):
    import agent as agent_mod
    from backend.chatflow import maybe_attach_episodic_summary

    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _boom)
    record = {"id": "c1", "messages": _long_history(16)}
    assert maybe_attach_episodic_summary(record) == record
