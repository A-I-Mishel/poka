"""Deterministic unknown-identity answers (Fix 3).

"who am i?" with no stored name is answered WITHOUT a model call —
weak tiers invent names ("You're Currently!") instead of admitting
ignorance. With a stored name, or attachments in play, the normal
model path answers untouched.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.flow import turns as turns_mod
from backend.flow.stages import _is_user_identity_question


@pytest.fixture()
def _user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "identity-flow-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from services import memory as mem
    from services.files import FileStore
    from services.storage import UserStore

    mem.set_memory_dir("")
    ctx = UserContext(user_id="identity-flow-user",
                      user_store=UserStore("identity-flow-user"),
                      file_store=FileStore("identity-flow-user"),
                      limit_key="identity-flow-user", source="env")
    try:
        yield ctx
    finally:
        mem.set_memory_dir("")


def test_detector_positives():
    for text in ("who am i", "Who am i?", "hey, who am i?",
                 "what is my name", "what's my name", "whats my name?",
                 "do you know my name", "do u know my name?",
                 "what do you call me", "tell me my name",
                 "Hello, who am I?!"):
        assert _is_user_identity_question(text) is True, text


def test_detector_negatives():
    for text in ("who are you", "what is your name", "whats your name?",
                 "what is my exam date", "who am i in this essay about kings",
                 "", "   ", "hey", "who am i " + "very " * 20 + "confused"):
        assert _is_user_identity_question(text) is False, text


def test_unknown_identity_answers_without_model(_user, monkeypatch):
    import agent as agent_mod

    calls = []

    def _boom(*a, **k):
        calls.append(1)
        pytest.fail("no model call allowed")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _boom)
    out = turns_mod.run_chat(_user, "who am i")
    assert out["active_tier"] == "identity"
    assert out["task_type"] == "simple"
    assert "don't know your name" in out["message"]["content"]
    assert calls == []
    # Persisted like a normal turn (user + assistant).
    stored, _warnings = _user.user_store.load_chats()
    assert [m["role"] for m in stored.get("current", [])] == ["user", "assistant"]


def test_stored_name_takes_model_path(_user, monkeypatch):
    import agent as agent_mod
    from types import SimpleNamespace
    from services import memory as mem

    mem.set_memory_dir(str(_user.user_store.root))
    mem.update_memory_incremental([{"role": "user", "content": "my name is sam"}])
    calls = []

    def _answer(*a, **k):
        calls.append(1)
        return SimpleNamespace(content="You are Sam.", tool_calls=[])

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _answer)
    out = turns_mod.run_chat(_user, "who am i")
    assert out["active_tier"] != "identity"
    assert calls, "stored name turns use the model"


def test_canned_ask_rearms_bare_name(_user, monkeypatch):
    import agent as agent_mod
    from types import SimpleNamespace
    from services import memory as mem

    monkeypatch.setattr(
        agent_mod, "_invoke_bounded",
        lambda *a, **k: SimpleNamespace(content="Noted.", tool_calls=[]))
    turns_mod.run_chat(_user, "who am i")
    turns_mod.run_chat(_user, "mishel")
    mem.set_memory_dir(str(_user.user_store.root))
    try:
        vault = mem.load_structured_memory()
    finally:
        mem.set_memory_dir("")
    assert vault.get("user_name") == "Mishel"
    # And now the identity question resolves from memory via the model.
    out = turns_mod.run_chat(_user, "who am i")
    assert out["active_tier"] != "identity"
