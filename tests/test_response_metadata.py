"""Response metadata & provenance regression tests (Phase 4A).

Covers persisted assistant metadata (model/mode/searched/tools):
additive schema, truthful values, legacy tolerance, isolation.

Conventions match the existing suite: stubbed identity + stubbed
answer_with_fallback for AppTest, FakeLLM scripts for the agent layer,
no live model calls, no quota spent.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent

# Bind the app's from-imports to the REAL service functions before any
# test below stubs services.identity.get_current_user (see the
# import-order note in test_force_search_flow.py).
import application.session  # noqa: F401
import services.auth  # noqa: F401
import ui.chat  # noqa: F401
import ui.components  # noqa: F401
import ui.composer  # noqa: F401
import ui.sidebar  # noqa: F401
import ui.uploads  # noqa: F401
from services.storage import UserStore, clean_messages
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
    """Scripted stand-in: items are text, (text, tool_calls), or Exceptions."""

    def __init__(self, script):
        self.script = list(script)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if self.script:
            item = self.script.pop(0)
        else:
            item = ("ok", [])
        if isinstance(item, Exception):
            raise item
        text, calls = item if isinstance(item, tuple) else (item, [])
        return SimpleNamespace(content=text, tool_calls=calls)


class SearchStub:
    name = "web_search"

    def invoke(self, args):
        # STATUS= prefix so _execute_tool_call passes it through tagged,
        # matching the real tool's contract that _note_search detects.
        return "STATUS=OK\n[1] T \u2014 D\nURL: https://example.com/a"


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


def _meta_spans(at):
    md = " ".join(str(m.value) for m in at.markdown)
    return re.findall(r'<span class="poka-time">(.*?)</span>', md)


# -- storage cleaner policy -------------------------------------------

def test_metadata_round_trip():
    msgs = [
        {"role": "user", "content": "hi", "time": "2026-01-01T00:00:00+00:00",
         "attachments": [{"id": "a" * 16, "kind": "pdf", "name": "r.pdf"}]},
        {"role": "assistant", "content": "hello", "time": "2026-01-01T00:00:01+00:00",
         "model": "Gemini 3.6 Flash", "mode": "deep", "searched": True,
         "tools": ["web_search", "read_pdf"]},
        {"role": "assistant", "content": "plain", "mode": "fast", "searched": False},
    ]
    out = clean_messages(msgs)
    assert out[0]["attachments"] == [{"id": "a" * 16, "kind": "pdf", "name": "r.pdf"}]
    assert out[0].get("model") is None  # user messages carry no metadata
    assert out[1]["model"] == "Gemini 3.6 Flash"
    assert out[1]["mode"] == "deep"
    assert out[1]["searched"] is True
    assert out[1]["tools"] == ["web_search", "read_pdf"]
    assert out[2]["mode"] == "fast"
    assert out[2]["searched"] is False
    assert "tools" not in out[2]


def test_cleaner_policy_drops_unknown_and_mistyped():
    msgs = [{
        "role": "assistant", "content": "x",
        "model": 123, "mode": "turbo", "searched": "yes",
        "tools": ["read_pdf", 123, "", "x" * 100, "ok"],
        "bogus": "drop me", "tokens": 999,
    }]
    out = clean_messages(msgs)
    assert out == [{
        "role": "assistant", "content": "x",
        "tools": ["read_pdf", "x" * 64, "ok"],
    }]
    assert clean_messages([{"role": "assistant", "content": "x",
                             "tools": []}])[0].get("tools") is None
    assert clean_messages([{"role": "assistant", "content": "x",
                             "tools": "web_search"}])[0].get("tools") is None
    assert clean_messages([{"role": "assistant", "content": "x",
                             "searched": 1}])[0].get("searched") is None
    many = [{"role": "assistant", "content": "x",
             "tools": [f"t{i}" for i in range(25)]}]
    assert len(clean_messages(many)[0]["tools"]) == 20


def test_legacy_messages_pass_through():
    legacy = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo", "time": "old"},
        {"role": "assistant", "content": "img", "image": "/tmp/x.png"},
        {"nope": True},
        "junk",
    ]
    out = clean_messages(legacy)
    assert [m["role"] for m in out] == ["user", "assistant", "assistant"]
    assert out[0] == {"role": "user", "content": "hi"}
    assert "model" not in out[1] and "searched" not in out[1]


def test_save_reload_preserves_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    msgs = [{"role": "assistant", "content": "hi",
             "model": "Muse Spark 1.3", "mode": "fast",
             "searched": False, "tools": ["web_search"]}]
    UserStore("alice").save_chats([], msgs)
    loaded, warnings = UserStore("alice").load_chats()
    assert warnings == []
    assert loaded["current"][0]["model"] == "Muse Spark 1.3"
    assert loaded["current"][0]["tools"] == ["web_search"]


def test_metadata_isolated_per_user(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    msgs = [{"role": "assistant", "content": "hi", "model": "T",
             "mode": "deep", "searched": True}]
    UserStore("alice").save_chats([], msgs)
    bob, _ = UserStore("bob").load_chats()
    assert bob == {"chats": [], "current": []}


def test_export_ignores_metadata():
    from ui.components import _export_chat_to_markdown
    plain = [{"role": "user", "content": "q", "time": ""},
             {"role": "assistant", "content": "a", "time": ""}]
    rich = [{"role": "user", "content": "q", "time": ""},
            {"role": "assistant", "content": "a", "time": "",
             "model": "T", "mode": "deep", "searched": True,
             "tools": ["web_search"]}]
    assert _export_chat_to_markdown(plain) == _export_chat_to_markdown(rich)
    assert "Web search" not in _export_chat_to_markdown(rich)


# -- agent-layer tool provenance --------------------------------------

def test_run_tool_loop_records_forced_search(monkeypatch):
    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    used: list = []
    out = agent.run_tool_loop(
        FakeLLM(["done"]), "news please", [], force_web_search=True,
        used_tools=used,
    )
    assert used == ["web_search"]
    assert "Sources consulted:" in out


def test_run_tool_loop_records_in_order_deduped(monkeypatch):
    class PdfStub:
        name = "read_pdf"

        def invoke(self, args):
            return "stubbed pdf text"

    monkeypatch.setitem(agent.TOOL_MAP, "read_pdf", PdfStub())
    used: list = []
    fake = FakeLLM([
        ("go", [{"name": "web_search", "args": {"query": "x"}},
                {"name": "read_pdf", "args": {"upload_id": "a" * 16}},
                {"name": "web_search", "args": {"query": "x"}}]),
        "final",
    ])
    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    agent.run_tool_loop(fake, "q", [], used_tools=used)
    assert used == ["web_search", "read_pdf"]


def test_run_tool_loop_ignores_unknown_tools():
    used: list = []
    fake = FakeLLM([
        ("go", [{"name": "nope-tool", "args": {}}]),
        "final",
    ])
    out = agent.run_tool_loop(fake, "q", [], used_tools=used)
    assert used == []
    assert out == "final"


def test_run_tool_loop_no_tools_empty():
    used: list = []
    out = agent.run_tool_loop(FakeLLM(["just text"]), "q", [], used_tools=used)
    assert out == "just text"
    assert used == []


def test_planning_passes_tools_through(monkeypatch):
    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    from agent.planning import plan_then_execute

    used: list = []
    fake = FakeLLM([
        "1. search first",
        ("go", [{"name": "web_search", "args": {"query": "x"}}]),
        "final",
    ])
    out = plan_then_execute(fake, "q", [], used_tools=used)
    assert "final" in out
    assert used == ["web_search"]


def test_failed_tier_keeps_partial_tools(monkeypatch):
    # Mid-task failover continues the SAME loop on the next tier instead
    # of restarting: the executed search genuinely backs the final
    # answer, so its provenance is kept (and no quota is spent
    # re-running it) rather than rolled back.
    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    flaky = FakeLLM([
        ("go", [{"name": "web_search", "args": {"query": "x"}}]),
        RuntimeError("tier blew up"),
    ])
    fine = FakeLLM(["fine"])
    out = agent.answer_with_fallback(
        "latest AI news today",
        tiers=[("bad", lambda: flaky), ("good", lambda: fine)],
        raw_messages=[],
    )
    assert out["output"].startswith("fine")
    assert "example.com/a" in out["output"]
    assert out["active_tier"] == "good"
    assert out["tools_used"] == ["web_search"]
    assert any(s["url"] == "https://example.com/a" for s in out["sources"])


def test_answer_reports_tools_used(monkeypatch):
    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    fake = FakeLLM([
        ("checking", [{"name": "web_search", "args": {"query": "ai news"}}]),
        "here is the news",
    ])
    out = agent.answer_with_fallback(
        "latest AI news today", tiers=_tiers(fake), raw_messages=[]
    )
    assert out["tools_used"] == ["web_search"]
    simple = agent.answer_with_fallback(
        "hello", tiers=_tiers(FakeLLM(["hi"])), raw_messages=[]
    )
    assert simple["tools_used"] == []


# -- AppTest end to end -----------------------------------------------

def test_send_persists_deep_search_metadata(monkeypatch):
    _stub_app_agent(monkeypatch, active_tier="Gemini 3.6 Flash",
                    task_type="research", tools_used=["web_search"])
    at = _fresh_app()
    at.session_state.deep_mode = True
    at.session_state.force_search = True
    at.run(timeout=60)
    at.text_input(key="composer_input_0").set_value("mars news").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assistant = [m for m in at.session_state.messages if m["role"] == "assistant"]
    assert len(assistant) == 1
    meta = assistant[0]
    assert meta["model"] == "Gemini 3.6 Flash"
    assert meta["mode"] == "deep"
    assert meta["searched"] is True
    assert meta["tools"] == ["web_search"]
    assert at.session_state["force_search"] is False
    # Meta row renders via history on the following run (same as the
    # long-standing time/copy row behavior).
    at.run(timeout=60)
    assert not at.exception
    spans = _meta_spans(at)
    assert any("Gemini 3.6 Flash" in s and "Deep" in s
               and "Web search" in s and "1 tool" in s for s in spans)


def test_send_persists_fast_normal_metadata(monkeypatch):
    _stub_app_agent(monkeypatch, active_tier="Muse Spark 1.3")
    at = _fresh_app()
    at.text_input(key="composer_input_0").set_value("hello").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["model"] == "Muse Spark 1.3"
    assert meta["mode"] == "fast"
    assert meta["searched"] is False
    assert "tools" not in meta
    assert not any("Web search" in s for s in _meta_spans(at))


def test_auto_search_output_not_labeled_forced(monkeypatch):
    _stub_app_agent(
        monkeypatch, active_tier="T",
        output="answer\nSources consulted:\n[1] X \u2014 https://example.com\n",
    )
    at = _fresh_app()
    at.text_input(key="composer_input_0").set_value("news").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["searched"] is False
    assert not any("Web search" in s for s in _meta_spans(at))


def test_legacy_messages_render_without_meta(monkeypatch):
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo", "time": "2026-01-01T00:00:00+00:00"},
        {"role": "assistant", "content": "old", "model": 1, "mode": "x",
         "searched": "yes", "tools": "web_search", "bogus": 1},
    ]
    at.run(timeout=120)
    assert not at.exception
    for span in _meta_spans(at):
        assert "\u00b7" not in span


def test_edit_generates_fresh_metadata(monkeypatch):
    _stub_app_agent(monkeypatch, active_tier="NewTier")
    at = _fresh_app()
    at.session_state.messages = [
        {"role": "user", "content": "old q"},
        {"role": "assistant", "content": "stale", "model": "StaleTier",
         "mode": "fast", "searched": True, "tools": ["read_pdf"]},
    ]
    at.run(timeout=120)
    at.button(key="edit-0").click().run(timeout=120)
    assert not at.exception, f"edit failed: {at.exception}"
    assert at.session_state.messages == []
    at.text_input(key="composer_input_0").set_value("new q").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["model"] == "NewTier"
    assert meta["searched"] is False
    assert "tools" not in meta


def test_retry_records_actual_retry_request(monkeypatch):
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
                "task_type": "simple", "tools_used": ["web_search"]}

    monkeypatch.setattr(agent, "answer_with_fallback", flaky)
    at = _fresh_app()
    at.text_input(key="composer_input_0").set_value("go").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assert at.session_state["last_failed"]
    at.button(key="retry-main").click().run(timeout=120)
    assert not at.exception, f"retry failed: {at.exception}"
    assistant = [m for m in at.session_state.messages if m["role"] == "assistant"]
    assert len(assistant) == 1
    assert assistant[0]["content"] == "recovered"
    assert assistant[0]["model"] == "RetryTier"
    assert assistant[0]["searched"] is False
    assert assistant[0]["tools"] == ["web_search"]
