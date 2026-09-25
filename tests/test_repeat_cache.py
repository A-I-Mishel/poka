"""Exact-repeat cache trial (opt-in, off by default).

Identical text asked twice reuses the last clean answer with zero
calls — but only when enabled, and never for teaching/vision/
attachment turns. Kill-switch: PLUTO_REPEAT_CACHE.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.flow import turns as turns_mod
from backend.flow.stages import (
    _repeat_cache_enabled,
    _repeat_cache_key,
)


@pytest.fixture()
def _user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "repeat-flow-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.delenv("PLUTO_REPEAT_CACHE", raising=False)
    from backend.deps import UserContext
    from services import memory as mem
    from services.files import FileStore
    from services.storage import UserStore

    mem.set_memory_dir("")
    ctx = UserContext(user_id="repeat-flow-user",
                      user_store=UserStore("repeat-flow-user"),
                      file_store=FileStore("repeat-flow-user"),
                      limit_key="repeat-flow-user", source="env")
    try:
        yield ctx
    finally:
        mem.set_memory_dir("")


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PLUTO_REPEAT_CACHE", raising=False)
    assert _repeat_cache_enabled() is False
    monkeypatch.setenv("PLUTO_REPEAT_CACHE", "1")
    assert _repeat_cache_enabled() is True


def test_key_varies_by_user_mode_tier():
    k = _repeat_cache_key("hello there", "u1", False, "")
    assert k
    assert _repeat_cache_key("hello there", "u2", False, "") != k
    assert _repeat_cache_key("hello there", "u1", True, "") != k
    assert _repeat_cache_key("hello there", "u1", False, "Groq") != k
    assert _repeat_cache_key("  HELLO there ", "u1", False, "") == k


def test_put_get_roundtrip_and_expiry():
    from backend.flow import stages as stages_mod

    stages_mod._repeat_cache.clear()
    key = _repeat_cache_key("q", "u", False, "")
    assert stages_mod._repeat_cache_get(key) is None
    stages_mod._repeat_cache_put(key, {"content": "a", "tier": "t", "task_type": "s"})
    assert stages_mod._repeat_cache_get(key) == {"content": "a", "tier": "t", "task_type": "s"}
    # Expired entries read as misses.
    ts, value = stages_mod._repeat_cache[key]
    stages_mod._repeat_cache[key] = (ts - 9999.0, value)
    assert stages_mod._repeat_cache_get(key) is None
    stages_mod._repeat_cache.clear()


def test_repeat_turn_skips_model(_user, monkeypatch):
    import agent as agent_mod
    from types import SimpleNamespace

    monkeypatch.setenv("PLUTO_REPEAT_CACHE", "1")
    calls = []

    def _answer(*a, **k):
        calls.append(1)
        return SimpleNamespace(content="Four.", tool_calls=[])

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _answer)
    first = turns_mod.run_chat(_user, "what is 2+2")
    n_after_first = len(calls)
    assert n_after_first >= 1
    second = turns_mod.run_chat(_user, "what is 2+2")
    assert len(calls) == n_after_first, "repeat must add zero model calls"
    assert second["message"]["content"] == first["message"]["content"]
    assert second["active_tier"] == first["active_tier"]


def test_repeat_off_calls_model_twice(_user, monkeypatch):
    import agent as agent_mod
    from types import SimpleNamespace

    monkeypatch.delenv("PLUTO_REPEAT_CACHE", raising=False)
    calls = []

    def _answer(*a, **k):
        calls.append(1)
        return SimpleNamespace(content="Four.", tool_calls=[])

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _answer)
    turns_mod.run_chat(_user, "what is 2+2")
    n_after_first = len(calls)
    turns_mod.run_chat(_user, "what is 2+2")
    assert len(calls) > n_after_first, "disabled cache runs the pipeline again"
