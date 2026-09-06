"""Force-search handoff regression tests: toggle -> agent.

Covers the UI-to-agent contract that render_assistant_response() must
capture the one-shot force_search flag BEFORE clearing it, so run_agent()
forwards the intended value to agent.answer_with_fallback, while later
messages stay normal (no leak).

Hermetic: stubbed identity + stubbed answer_with_fallback, no quota.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent

# Bind the app's from-imports to the REAL service functions before any
# test below stubs services.identity.get_current_user. Python from-imports
# capture whatever the source module holds at first import; this file runs
# before test_phase2.py, so without these imports app.py's first AppTest
# run would permanently bind the stub into services.auth and break the
# private-mode tests that run later.
import application.session  # noqa: F401
import services.auth  # noqa: F401
import ui.chat  # noqa: F401
import ui.components  # noqa: F401
import ui.composer  # noqa: F401
import ui.sidebar  # noqa: F401
import ui.uploads  # noqa: F401

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _stub_agent(monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )
    captured = {}

    def fake_answer(user_input, chat_history=None, **kwargs):
        captured["force_web_search"] = kwargs.get("force_web_search")
        return {"output": "ok", "active_tier": "T", "task_type": "simple"}

    monkeypatch.setattr(agent, "answer_with_fallback", fake_answer)
    return captured


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


def test_search_toggle_reaches_agent(monkeypatch):
    captured = _stub_agent(monkeypatch)
    at = _fresh_app()
    # Same state the plus-menu "Web search" toggle writes (uploads.py).
    at.session_state.force_search = True
    at.run(timeout=60)
    at.text_input(key="composer_input_0").set_value("latest mars news").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assert captured["force_web_search"] is True
    # One-shot: consumed, later messages stay normal.
    assert at.session_state["force_search"] is False


def test_normal_request_stays_normal(monkeypatch):
    captured = _stub_agent(monkeypatch)
    at = _fresh_app()
    at.text_input(key="composer_input_0").set_value("hello there").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assert captured["force_web_search"] is False


def test_search_does_not_leak_into_next_message(monkeypatch):
    captured = _stub_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.force_search = True
    at.run(timeout=60)
    at.text_input(key="composer_input_0").set_value("first with search").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"first send failed: {at.exception}"
    assert captured["force_web_search"] is True
    # Second, unrelated message: no toggle, must be a normal request.
    at.text_input(key="composer_input_1").set_value("second plain").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"second send failed: {at.exception}"
    assert captured["force_web_search"] is False
