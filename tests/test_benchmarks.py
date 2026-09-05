"""Orchestration benchmarks: measured call counts per scenario.

Uses scripted FakeLLMs (no network, no quota), so LLM latency figures
reflect local orchestration overhead only — call counts and token flows
are the real measurements. Run with -s to see the comparison table.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from services import context as ctx
from services.tokens import count_tokens
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("POKA_USER_ID", "bench-user")
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    ctx.set_current_user_id("bench-user")
    yield
    ctx.set_current_user_id(None)


@pytest.fixture(autouse=True)
def _clean_agent_state():
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent.ROUTER_STATS["rule"] = 0
    agent.ROUTER_STATS["llm"] = 0
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()


class FakeLLM:
    """Scripted stand-in: list items are text or (text, tool_calls)."""

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


class CallCounter:
    """Wraps agent._invoke_bounded to count LLM calls transparently."""

    def __init__(self, monkeypatch):
        self.llm_calls = 0
        self.context_tokens = 0
        real = agent._invoke_bounded

        def counting(llm, messages, timeout=90.0, budget=None):
            self.llm_calls += 1
            try:
                self.context_tokens += sum(
                    count_tokens(str(getattr(m, "content", m))) for m in messages
                )
            except Exception:
                pass
            return real(llm, messages, timeout=timeout, budget=budget)

        monkeypatch.setattr(agent, "_invoke_bounded", counting)


def _tiers(fake):
    return [("fake", lambda: fake)]


def test_bench_simple(env, monkeypatch):
    counter = CallCounter(monkeypatch)
    fake = FakeLLM(["hello back"])
    out = agent.answer_with_fallback("hello", tiers=_tiers(fake), raw_messages=[])
    assert out["output"] == "hello back"
    assert counter.llm_calls == 1
    print(f"\n[bench] simple: llm={counter.llm_calls}")


def test_bench_search(env, monkeypatch):
    counter = CallCounter(monkeypatch)

    class SearchStub:
        name = "web_search"

        def invoke(self, args):
            return "stubbed results"

    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    fake = FakeLLM([
        ("checking", [{"name": "web_search", "args": {"query": "ai news"}}]),
        "here is the news",
    ])
    out = agent.answer_with_fallback(
        "latest AI news today", tiers=_tiers(fake), raw_messages=[]
    )
    assert "news" in out["output"]
    assert counter.llm_calls == 2
    print(f"\n[bench] search: llm={counter.llm_calls}")


def test_bench_pdf(env, monkeypatch):
    from services.files import FileStore

    counter = CallCounter(monkeypatch)
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
    meta = FileStore("bench-user").save_upload(pdf, "doc.pdf")
    fake = FakeLLM([
        ("reading", [{"name": "read_pdf", "args": {"upload_id": meta.id}}]),
        "document summary here",
    ])
    out = agent.answer_with_fallback(
        f"summarize the pdf {meta.id}", tiers=_tiers(fake), raw_messages=[]
    )
    assert counter.llm_calls == 2
    print(f"\n[bench] pdf: llm={counter.llm_calls}")


def test_bench_csv(env, monkeypatch):
    from services.files import FileStore

    counter = CallCounter(monkeypatch)
    meta = FileStore("bench-user").save_upload(b"a,b\n1,2\n3,4\n", "d.csv")
    fake = FakeLLM([
        ("analyzing", [{"name": "analyze_csv", "args": {"upload_id": meta.id}}]),
        "analysis done",
    ])
    out = agent.answer_with_fallback(
        "analyze my csv data", tiers=_tiers(fake), raw_messages=[]
    )
    assert "analysis done" in out["output"]
    assert counter.llm_calls == 2
    print(f"\n[bench] csv: llm={counter.llm_calls}")


def test_bench_pptx_fast_vs_deep(env, monkeypatch):
    from services import context as ctx
    from services.files import FileStore

    ctx.set_current_user_id("bench-user")

    def run(deep):
        counter = CallCounter(monkeypatch)
        tool_turn = (
            "building",
            [{
                "name": "create_pptx",
                "args": {"topic": "Space", "content": "Intro\n- vast\n\nStars\n- bright"},
            }],
        )
        script = [tool_turn, "deck ready"] if not deep else [
            "1. outline\n2. generate", tool_turn, "deck ready", "[PASS]",
        ]
        fake = FakeLLM(script)
        t0 = time.time()
        out = agent.answer_with_fallback(
            "make a presentation on space",
            tiers=_tiers(fake),
            raw_messages=[],
            deep_mode=deep,
        )
        return out, counter.llm_calls, time.time() - t0

    out_fast, fast_calls, fast_t = run(False)
    out_deep, deep_calls, deep_t = run(True)
    print(
        f"\n[bench] pptx fast: llm={fast_calls} t={fast_t:.2f}s | "
        f"deep: llm={deep_calls} t={deep_t:.2f}s"
    )
    assert fast_calls == 2, fast_calls          # loop invoke + final (no plan/reflect)
    assert deep_calls == 4, deep_calls          # plan + loop x2 + reflect
    assert deep_calls > fast_calls
    assert "deck ready" in out_fast["output"]
    from services.files import FileStore

    assert len(FileStore("bench-user").list_outputs()) >= 1
    ctx.set_current_user_id(None)


def test_bench_long_conversation_summarizes(env, monkeypatch):
    counter = CallCounter(monkeypatch)
    history = []
    for i in range(15):
        history.append({"role": "user", "content": f"question {i}"})
        history.append({"role": "assistant", "content": f"answer {i}"})
    fake = FakeLLM([
        "prior summary",
        ("checking", [{"name": "web_search", "args": {"query": "x"}}]),
        "final",
    ])

    class SearchStub:
        name = "web_search"

        def invoke(self, args):
            return "stub"

    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    out = agent.answer_with_fallback(
        "latest news please", tiers=_tiers(fake), raw_messages=history
    )
    first_prompt = str(fake.calls[0][0].content)
    assert "Summarize this conversation" in first_prompt
    assert out["output"] == "final"
    print(f"\n[bench] long-convo(30 msgs): llm={counter.llm_calls}")


def test_bench_router_savings():
    before_rule = agent.ROUTER_STATS["rule"]
    before_llm = agent.ROUTER_STATS["llm"]
    assert agent.rule_route("hello") == "simple"
    assert agent.rule_route("make a presentation") == "creative"
    assert agent.rule_route("what is the meaning of flibbertigibbet?") is None
    # Router itself performs no model calls; stats only move in answer flow.
    assert agent.ROUTER_STATS["rule"] == before_rule
    assert agent.ROUTER_STATS["llm"] == before_llm
