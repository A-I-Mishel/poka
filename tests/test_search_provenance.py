"""Search provenance regression tests (Phase 4C).

Intent (searched) vs execution (search_executed) vs structured sources
are recorded only from execution data — never inferred from markdown.
Hermetic: stubbed tools/LLMs, no live search, no quota.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent

# Bind the app's from-imports to the REAL service functions before any
# AppTest run (see the import-order note in test_force_search_flow.py).
import application.session  # noqa: F401
import services.auth  # noqa: F401
import ui.chat  # noqa: F401
import ui.components  # noqa: F401
import ui.composer  # noqa: F401
import ui.sidebar  # noqa: F401
import ui.uploads  # noqa: F401
from services.storage import UserStore, clean_messages, clean_source_record
from types import SimpleNamespace

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _clean_agent_state():
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        item = self.script.pop(0) if self.script else ("ok", [])
        if isinstance(item, Exception):
            raise item
        text, calls = item if isinstance(item, tuple) else (item, [])
        return SimpleNamespace(content=text, tool_calls=calls)


class SearchStub:
    name = "web_search"

    def invoke(self, args):
        return (
            "STATUS=OK\n"
            '[1] Real Story \u2014 real.example\n'
            "URL: https://real.example/s\n"
            "Snippet: happened today\n"
            '[2] Second Take \u2014 second.example\n'
            "URL: https://second.example/t\n"
        )


class EmptySearchStub:
    name = "web_search"

    def invoke(self, args):
        return "STATUS=EMPTY tool=web_search: no results found."


def _tiers(fake):
    return [("fake", lambda: fake)]


def _stub_app_agent(monkeypatch, **extra):
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )
    payload = {"output": "ok", "active_tier": "T", "task_type": "simple"}
    payload.update(extra)

    def fake_answer(user_input, chat_history=None, **kwargs):
        return dict(payload)

    monkeypatch.setattr(agent, "answer_with_fallback", fake_answer)


def _fresh_app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.session_state.messages = []
    at.session_state.chats = []
    at.run(timeout=60)
    assert not at.exception
    return at


def _md(at):
    return " ".join(str(m.value) for m in at.markdown)


# -- agent-layer capture ----------------------------------------------

def test_forced_search_captures_structured_sources(monkeypatch):
    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    used: list = []
    sources: list = []
    out = agent.run_tool_loop(
        FakeLLM(["done"]), "news please", [], force_web_search=True,
        used_tools=used, used_sources=sources,
    )
    assert used == ["web_search"]
    assert [(s["title"], s["url"], s["domain"]) for s in sources] == [
        ("Real Story", "https://real.example/s", "real.example"),
        ("Second Take", "https://second.example/t", "second.example"),
    ]
    assert isinstance(out, str)


def test_forced_search_empty_fabricates_nothing(monkeypatch):
    monkeypatch.setitem(agent.TOOL_MAP, "web_search", EmptySearchStub())
    used: list = []
    sources: list = []
    agent.run_tool_loop(
        FakeLLM(["done"]), "news please", [], force_web_search=True,
        used_tools=used, used_sources=sources,
    )
    assert used == ["web_search"]  # the call happened
    assert sources == []  # but no sources existed


def test_automatic_search_captures_without_intent(monkeypatch):
    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    fake = FakeLLM([
        ("looking", [{"name": "web_search", "args": {"query": "q"}}]),
        "It happened.",
    ])
    out = agent.answer_with_fallback(
        "latest AI news today", tiers=_tiers(fake), raw_messages=[]
    )
    assert "sources" in out and len(out["sources"]) == 2
    assert out.get("searched") is None  # intent lives at the chat layer only
    assert out["tools_used"] == ["web_search"]


def test_no_search_no_provenance():
    out = agent.answer_with_fallback(
        "hello", tiers=_tiers(FakeLLM(["hi"])), raw_messages=[]
    )
    assert out["tools_used"] == []
    assert out["sources"] == []


def test_sources_deduped_capped_across_rounds(monkeypatch):
    class MultiStub:
        name = "web_search"

        def invoke(self, args):
            return (
                "STATUS=OK\n"
                "[1] A \u2014 a.example\nURL: https://a.example/1\n"
                "[2] B \u2014 b.example\nURL: HTTPS://B.EXAMPLE/2/\n"
            )

    monkeypatch.setitem(agent.TOOL_MAP, "web_search", MultiStub())
    fake = FakeLLM([
        ("one", [{"name": "web_search", "args": {"query": "x"}}]),
        ("two", [{"name": "web_search", "args": {"query": "y"}},
                 {"name": "web_search", "args": {"query": "x"}}]),
        "final",
    ])
    sources: list = []
    agent.run_tool_loop(fake, "q", [], used_tools=[], used_sources=sources)
    assert [s["url"] for s in sources] == [
        "https://a.example/1", "HTTPS://B.EXAMPLE/2/"]


def test_source_cap_enforced(monkeypatch):
    from services.storage import MAX_SOURCES

    items = "".join(
        f"[{i}] T{i} \u2014 e.example\nURL: https://e.example/{i}\n"
        for i in range(1, 12)
    )

    class ManyStub:
        name = "web_search"

        def invoke(self, args):
            return "STATUS=OK\n" + items

    monkeypatch.setitem(agent.TOOL_MAP, "web_search", ManyStub())
    sources: list = []
    agent.run_tool_loop(
        FakeLLM(["done"]), "q", [], force_web_search=True,
        used_sources=sources,
    )
    assert len(sources) == MAX_SOURCES == 6


# -- cleaner policy -----------------------------------------------------

def test_clean_source_record_policy():
    good = clean_source_record({"title": "T", "url": "https://e.example/a",
                                "domain": "wrong.example"})
    assert good == {"title": "T", "url": "https://e.example/a",
                    "domain": "e.example"}
    assert clean_source_record({"url": "https://e.example/a"})["title"] == "e.example"
    for bad in [None, "x", 123, {}, {"url": ""},
                {"url": "javascript:alert(1)"},
                {"url": "data:text/html,hi"},
                {"url": "file:///etc/passwd"},
                {"url": "notaurl"},
                {"url": "https://"},
                {"url": "https://e.example/a b"},
                {"url": "x" * 600},
                {"url": "ftp://e.example/a"}]:
        assert clean_source_record(bad) is None, bad
    long_title = clean_source_record({"title": "t" * 200,
                                      "url": "https://e.example/a"})
    assert len(long_title["title"]) == 120


def test_clean_messages_provenance_policy():
    msgs = [{
        "role": "assistant", "content": "x",
        "search_executed": True,
        "sources": [
            {"title": "A", "url": "https://a.example/1", "domain": "a.example"},
            {"title": "X", "url": "javascript:evil()"},
            "junk",
            {"title": "B", "url": "https://b.example/2", "domain": "b.example"},
            {"title": "A2", "url": "https://a.example/1", "domain": "a.example"},
        ],
    }]
    out = clean_messages(msgs)
    # storage keeps validated records; UI-layer dedup already ran upstream
    assert [s["url"] for s in out[0]["sources"]] == [
        "https://a.example/1", "https://b.example/2", "https://a.example/1"]
    assert out[0]["search_executed"] is True
    bad_flag = clean_messages(
        [{"role": "assistant", "content": "x", "search_executed": "yes"}])
    assert bad_flag[0].get("search_executed") is None
    empty_src = clean_messages(
        [{"role": "assistant", "content": "x", "sources": []}])
    assert empty_src[0].get("sources") is None
    legacy = clean_messages([{"role": "assistant", "content": "x"}])
    assert "search_executed" not in legacy[0] and "sources" not in legacy[0]


def test_provenance_round_trip_and_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    msgs = [{"role": "assistant", "content": "hi", "model": "T",
             "mode": "deep", "searched": True, "search_executed": True,
             "tools": ["web_search"],
             "sources": [{"title": "A", "url": "https://a.example/1",
                          "domain": "a.example"}]}]
    UserStore("alice").save_chats([], msgs)
    loaded, warnings = UserStore("alice").load_chats()
    assert warnings == []
    got = loaded["current"][0]
    assert got["search_executed"] is True
    assert got["sources"] == [{"title": "A", "url": "https://a.example/1",
                               "domain": "a.example"}]
    bob, _ = UserStore("bob").load_chats()
    assert bob == {"chats": [], "current": []}


def test_export_ignores_provenance():
    from ui.components import _export_chat_to_markdown
    base = [{"role": "assistant", "content": "a", "time": ""}]
    rich = [{"role": "assistant", "content": "a", "time": "",
             "search_executed": True,
             "sources": [{"title": "A", "url": "https://a.example/1",
                          "domain": "a.example"}]}]
    assert _export_chat_to_markdown(base) == _export_chat_to_markdown(rich)


# -- AppTest: cases A-E ---------------------------------------------------

SRC = {"title": "Mars News", "url": "https://example.com/mars",
       "domain": "example.com"}


def test_case_a_forced_search_shows_provenance(monkeypatch):
    _stub_app_agent(monkeypatch, active_tier="Gemini 3.6 Flash",
                    task_type="research", tools_used=["web_search"],
                    sources=[dict(SRC)])
    at = _fresh_app()
    at.session_state.deep_mode = True
    at.session_state.force_search = True
    at.run(timeout=60)
    at.text_input(key="composer_input_0").set_value("mars news").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["searched"] is True
    assert meta["search_executed"] is True
    assert meta["sources"] == [dict(SRC)]
    at.run(timeout=60)
    body = _md(at)
    assert 'class="poka-sources"' in body
    assert "Mars News" in body and "example.com" in body
    assert "https://example.com/mars" in body
    spans = re.findall(r'<span class="poka-time">(.*?)</span>', body)
    assert any("Web search" in s and "Deep" in s for s in spans)


def test_case_b_normal_response_no_indicator(monkeypatch):
    _stub_app_agent(monkeypatch, active_tier="Muse Spark 1.3")
    at = _fresh_app()
    at.text_input(key="composer_input_0").set_value("hello").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    at.run(timeout=60)
    body = _md(at)
    assert 'class="poka-sources"' not in body
    assert not any("Web search" in s
                   for s in re.findall(r'<span class="poka-time">(.*?)</span>', body))
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["searched"] is False
    assert meta["search_executed"] is False
    assert "sources" not in meta


def test_case_c_automatic_search_not_forced(monkeypatch):
    _stub_app_agent(
        monkeypatch, active_tier="T",
        output="answer\nSources consulted:\n[1] X \u2014 https://example.com\n",
        tools_used=["web_search"], sources=[dict(SRC)],
    )
    at = _fresh_app()
    at.text_input(key="composer_input_0").set_value("news").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["searched"] is False  # never conflated with intent
    assert meta["search_executed"] is True
    at.run(timeout=60)
    assert 'class="poka-sources"' in _md(at)


def test_case_d_legacy_renders_without_provenance(monkeypatch):
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "old answer",
         "time": "2026-01-01T00:00:00+00:00",
         "model": "OldTier", "mode": "fast", "searched": True},
    ]
    at.run(timeout=120)
    assert not at.exception
    body = _md(at)
    assert 'class="poka-sources"' not in body
    spans = re.findall(r'<span class="poka-time">(.*?)</span>', body)
    assert spans and not any("Web search" in s for s in spans)


def test_case_e_retry_gets_fresh_provenance(monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )
    calls = {"n": 0}

    def flaky(user_input, chat_history=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"output": "recovered", "active_tier": "RetryTier",
                "task_type": "simple", "tools_used": ["web_search"],
                "sources": [dict(SRC)]}

    monkeypatch.setattr(agent, "answer_with_fallback", flaky)
    at = _fresh_app()
    at.session_state.messages = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "stale", "model": "Old",
         "mode": "fast", "searched": True, "search_executed": True,
         "tools": ["read_pdf"],
         "sources": [{"title": "S", "url": "https://stale.example/",
                      "domain": "stale.example"}]},
    ]
    at.run(timeout=60)
    at.text_input(key="composer_input_0").set_value("go").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    at.button(key="retry-main").click().run(timeout=120)
    assert not at.exception, f"retry failed: {at.exception}"
    assistant = [m for m in at.session_state.messages if m["role"] == "assistant"]
    assert len(assistant) == 2
    fresh = assistant[-1]
    assert fresh["content"] == "recovered"
    assert fresh["searched"] is False
    assert fresh["search_executed"] is True
    assert fresh["sources"] == [dict(SRC)]
    assert assistant[0]["sources"][0]["url"] == "https://stale.example/"


def test_edit_gets_fresh_provenance(monkeypatch):
    _stub_app_agent(monkeypatch, active_tier="NewTier", tools_used=[],
                    sources=[])
    at = _fresh_app()
    at.session_state.messages = [
        {"role": "user", "content": "old q"},
        {"role": "assistant", "content": "stale", "model": "Old",
         "mode": "fast", "searched": True, "search_executed": True,
         "sources": [{"title": "S", "url": "https://stale.example/",
                      "domain": "stale.example"}]},
    ]
    at.run(timeout=120)
    at.button(key="edit-0").click().run(timeout=120)
    assert not at.exception, f"edit failed: {at.exception}"
    at.text_input(key="composer_input_0").set_value("new q").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["model"] == "NewTier"
    assert meta["searched"] is False
    assert meta["search_executed"] is False
    assert "sources" not in meta


def test_theme_has_source_styles():
    import ui.theme as theme

    for token in (".poka-sources", ".poka-sources-head", ".poka-source-n",
                  ".poka-source-d", "overflow-wrap: anywhere"):
        assert token in theme.THEME_CSS
    import ui.chat as chat_mod
    import inspect

    rendered = inspect.getsource(chat_mod._sources_section)
    assert 'target="_blank"' in rendered
    assert 'rel="noopener noreferrer"' in rendered
