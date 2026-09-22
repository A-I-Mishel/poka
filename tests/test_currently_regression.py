"""Regression for reported 'Currently' defect (screenshot 22-Sep-2026).

Covers the three-layer fix:
- P0: poisoned vaults self-heal on load.
- P1: 'do you know what is my name?' hits deterministic guard.
- P2: model hallucinations are sanitized post-call.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import memory as mem
from backend.flow.stages import _is_user_identity_question


def test_detector_covers_reported_phrasing():
    for text in (
        "do you know what is my name?",
        "do you know whats my name",
        "do you know what's my name?",
        "do you know who am i?",
        "do you know me?",
        "do u know me",
    ):
        assert _is_user_identity_question(text) is True, text


def test_detector_still_rejects():
    for text in (
        "what is my exam date",
        "who am i in this essay about kings",
        "who are you",
        "what is your name",
    ):
        assert _is_user_identity_question(text) is False, text


def test_self_heal_purges_currently(tmp_path):
    mem.set_memory_dir(str(tmp_path))
    try:
        poison = {
            "preferences": {},
            "facts": [
                {"type": "name", "value": "Currently", "polarity": "positive",
                 "confidence": "low", "source": "inferred",
                 "date": "2026-09-21T23:53:34+00:00",
                 "key": "name: currently name"},
            ],
            "past_tasks": [],
            "user_name": "Currently",
            "_processed_hashes": [],
        }
        with open(tmp_path / "structured_memory.json", "w",
                   encoding="utf-8") as fh:
            json.dump(poison, fh)
        loaded = mem.load_structured_memory()
        assert loaded.get("user_name") is None
        assert [f for f in loaded.get("facts", [])
                if f.get("type") == "name"] == []
        # Persisted, so a second load stays clean.
        reloaded = mem.load_structured_memory()
        assert reloaded.get("user_name") is None
    finally:
        mem.set_memory_dir("")


def test_self_heal_recovers_valid_name(tmp_path):
    mem.set_memory_dir(str(tmp_path))
    try:
        poison = {
            "preferences": {},
            "facts": [
                {"type": "name", "value": "Mishel", "polarity": "positive",
                 "confidence": "high", "source": "explicit",
                 "date": "2026-09-22T00:00:00+00:00"},
                {"type": "name", "value": "Currently", "polarity": "positive",
                 "confidence": "low", "source": "inferred",
                 "date": "2026-09-21T23:53:34+00:00"},
            ],
            "past_tasks": [],
            "user_name": "Currently",
            "_processed_hashes": [],
        }
        with open(tmp_path / "structured_memory.json", "w",
                   encoding="utf-8") as fh:
            json.dump(poison, fh)
        loaded = mem.load_structured_memory()
        assert loaded.get("user_name") == "Mishel"
        assert [f.get("value") for f in loaded.get("facts", [])
                if f.get("type") == "name"] == ["Mishel"]
    finally:
        mem.set_memory_dir("")


def test_sanitize_hallucination(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "currently-regression-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from backend.flow import turns as turns_mod
    from services.files import FileStore
    from services.storage import UserStore

    ctx = UserContext(user_id="currently-regression-user",
                      user_store=UserStore("currently-regression-user"),
                      file_store=FileStore("currently-regression-user"),
                      limit_key="currently-regression-user", source="env")
    try:
        msg = {"role": "assistant",
               "content": 'Yes—I have you listed as "Currently."'}
        clean, tier, task = turns_mod._sanitize_identity_hallucination(
            ctx, "do you know what is my name?", msg, "Groq", "simple",
            False, False)
        assert tier == "identity"
        assert task == "simple"
        assert "don't know your name" in clean["content"]
        assert "Currently" not in clean["content"]
    finally:
        mem.set_memory_dir("")


def test_reported_phrasing_never_hits_model(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "currently-nomodel-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    import agent as agent_mod
    from backend.deps import UserContext
    from backend.flow import turns as turns_mod
    from services.files import FileStore
    from services.storage import UserStore

    ctx = UserContext(user_id="currently-nomodel-user",
                      user_store=UserStore("currently-nomodel-user"),
                      file_store=FileStore("currently-nomodel-user"),
                      limit_key="currently-nomodel-user", source="env")

    def _boom(*a, **k):
        pytest.fail("no model call allowed for nameless identity")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _boom)
    try:
        out = turns_mod.run_chat(ctx, "do you know what is my name?")
    finally:
        mem.set_memory_dir("")
    assert out["active_tier"] == "identity"
    assert "don't know your name" in out["message"]["content"]
