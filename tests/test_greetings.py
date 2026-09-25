"""Zero-call pure greetings (call saver, quality-neutral).

Bare greetings skip the cascade entirely: no model call, no tier use,
no quota. Guards: full-match only, evaluated after sticky
continuations (mid-teaching "hi" stays a session answer), pure text
only (attachments/images take the normal path), kill-switch via
PLUTO_GREETINGS=0. Any doubt fails open to the model.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.flow import turns as turns_mod
from backend.flow.stages import _greeting_reply, _is_pure_greeting


@pytest.fixture()
def _user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "greet-flow-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.setenv("PLUTO_GREETINGS", "1")
    from backend.deps import UserContext
    from services import memory as mem
    from services.files import FileStore
    from services.storage import UserStore

    mem.set_memory_dir("")
    ctx = UserContext(user_id="greet-flow-user",
                      user_store=UserStore("greet-flow-user"),
                      file_store=FileStore("greet-flow-user"),
                      limit_key="greet-flow-user", source="env")
    try:
        yield ctx
    finally:
        mem.set_memory_dir("")


def test_detector_positives():
    for text in ("hi", "Hi!", "hello", "HELLO?", "hey", "yo",
                 "good morning", "salam", "assalamualaikum", "hiii..."):
        assert _is_pure_greeting(text) is True, text


def test_detector_negatives():
    for text in ("", "   ", "how are you?", "hi, what is a vertex?",
                 "high", "history", "this", "ok",
                 "teach me slides", "yo check this proof"):
        assert _is_pure_greeting(text) is False, text


def test_reply_rotates_and_salam_variant():
    assert _greeting_reply("hi", "u1") in (
        "Hey! Good to see you — what are we working on?",
        "Hi there! What's on your mind?",
        "Hello! Ready when you are — what's up?",
    )
    assert "salam" in _greeting_reply("salam", "u1").lower()


def test_greeting_answers_without_model(_user, monkeypatch):
    import agent as agent_mod

    calls = []

    def _boom(*a, **k):
        calls.append(1)
        pytest.fail("no model call allowed")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _boom)
    out = turns_mod.run_chat(_user, "hi")
    assert out["active_tier"] == "greeting"
    assert out["task_type"] == "simple"
    assert out["message"]["content"]
    assert calls == []
    stored, _warnings = _user.user_store.load_chats()
    assert [m["role"] for m in stored.get("current", [])] == ["user", "assistant"]


def test_greeting_with_question_takes_model_path(_user, monkeypatch):
    import agent as agent_mod
    from types import SimpleNamespace

    calls = []

    def _answer(*a, **k):
        calls.append(1)
        return SimpleNamespace(content="A vertex is a node.", tool_calls=[])

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _answer)
    out = turns_mod.run_chat(_user, "hi, what is a vertex?")
    assert out["active_tier"] != "greeting"
    assert calls, "mixed messages use the model"


def test_mid_teaching_hi_stays_in_session(_user):
    from backend.chatflow import _is_teaching_continuation

    hist = [{"role": "assistant",
             "content": "📘 FILE: Lecture_01\nSlides: 1-1\n## Concept: Graph\n"
                        "**Source:** [slide 1]\nWhat is a vertex?"}]
    # Pending closing question: "hi" is a session answer, not a greeting.
    assert _is_teaching_continuation("hi", hist) is True


def test_kill_switch_restores_model_path(_user, monkeypatch):
    import agent as agent_mod
    from types import SimpleNamespace

    monkeypatch.setenv("PLUTO_GREETINGS", "0")
    calls = []

    def _answer(*a, **k):
        calls.append(1)
        return SimpleNamespace(content="Hello to you too.", tool_calls=[])

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _answer)
    out = turns_mod.run_chat(_user, "hi")
    assert out["active_tier"] != "greeting"
    assert calls, "kill-switch restores the model path"
