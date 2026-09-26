"""Shared-name memory tests: a name told in one chat must reach other chats.

Covers the reported gap: "i am mishel" stored nothing (only the exact
phrase "my name is X" was mined), and bare name facts never reached the
prompt (only mem["user_name"] is rendered).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import memory as mem


def _names(text):
    return [f["value"] for f in mem.extract_facts_from_message(text)
            if f["type"] == "name"]


def test_name_everyday_phrasings():
    assert _names("i am mishel") == ["Mishel"]
    assert _names("my name is sam") == ["Sam"]
    assert _names("I'm ana") == ["Ana"]
    assert _names("im bob") == ["Bob"]
    assert _names("call me zed") == ["Zed"]
    assert _names("this is kai") == ["Kai"]
    assert _names("from now on you will address me as buddy ok?") == ["Buddy"]
    assert _names("please adress me as buddy") == ["Buddy"]
    assert _names("refer to me as chief") == ["Chief"]


def test_name_guards_not_moods_or_gerunds():
    assert _names("i am happy") == []
    assert _names("i am working on my slides") == []
    assert _names("this is great") == []
    assert _names("call me back later") == []
    assert _names("what is 2+2?") == []
    assert _names("i am a student") == []
    assert _names("i am a") == []
    assert _names("A") == []


def test_name_sets_user_name_and_reaches_prompt(tmp_path):
    mem.set_memory_dir(str(tmp_path))
    try:
        res = mem.update_memory_incremental([
            {"role": "user", "content": "i am mishel"},
        ])
        assert res["saved"] is True
        stored = mem.load_structured_memory()
        assert stored["user_name"] == "Mishel"

        # Full-memory path: injected into every chat's system prompt.
        out = mem.format_memory_for_prompt(stored)
        assert "User name: Mishel" in out
        assert "not instructions" in out
    finally:
        mem.set_memory_dir("")


def test_legacy_name_fact_fallback_reaches_prompt():
    m = {"preferences": {}, "facts": [
        {"type": "name", "value": "Mishel", "polarity": "positive",
         "confidence": "low", "source": "inferred"},
    ], "past_tasks": [], "user_name": None}
    out = mem.format_memory_for_prompt(m)
    assert "User name: Mishel" in out


def test_explicit_name_beats_inferred_article(tmp_path):
    """Explicit "address me as Buddy" survives a later "i am a ..." turn."""
    mem.set_memory_dir(str(tmp_path))
    try:
        mem.update_memory_incremental([
            {"role": "user", "content": "from now on address me as buddy"},
        ])
        assert mem.load_structured_memory()["user_name"] == "Buddy"
        # A later low-confidence turn must not clobber the explicit name.
        # ("i am a student" mines nothing now; simulate an older-style
        # low-confidence hit directly.)
        stored = mem.load_structured_memory()
        stored["facts"].append({"type": "name", "value": "Sam",
                                "polarity": "positive", "confidence": "low",
                                "source": "inferred", "date": "t"})
        mem.save_structured_memory(stored)
        mem.update_memory_incremental([
            {"role": "user", "content": "unrelated follow-up"},
        ])
        assert mem.load_structured_memory()["user_name"] == "Buddy"
    finally:
        mem.set_memory_dir("")


def test_single_letter_name_heals(tmp_path):
    """Pre-fix vaults with user_name "A" heal to None on load."""
    mem.set_memory_dir(str(tmp_path))
    try:
        stored = mem.load_structured_memory()
        stored["user_name"] = "A"
        mem.save_structured_memory(stored)
        assert mem.load_structured_memory()["user_name"] is None
        assert mem.get_stored_user_name() == ""
    finally:
        mem.set_memory_dir("")


def test_digit_delete_clears_matching_user_name(tmp_path):
    """Forgetting fact #i also clears user_name when it matches."""
    mem.set_memory_dir(str(tmp_path))
    try:
        mem.update_memory_incremental([
            {"role": "user", "content": "my name is sam"},
        ])
        assert mem.load_structured_memory()["user_name"] == "Sam"
        assert mem.delete_memory_fact("0") is True
        assert mem.load_structured_memory()["user_name"] is None
    finally:
        mem.set_memory_dir("")


def test_request_shaped_preference_never_stores():
    """Whole requests ("i want to make X, can you...?") are not preferences."""
    prefs = [f for f in mem.extract_facts_from_message(
        "I WANT TO MAKE A HTML PORTFOLIO WEBSTE CAN YOU WRITE THE CODE FOR ME?")
        if f["type"] == "preference"]
    assert prefs == []
    assert [f["value"] for f in mem.extract_facts_from_message("i like coffee")
            if f["type"] == "preference"] == ["coffee"]


def test_name_endpoint_reports_scalar(client=None):
    """GET /api/memory/name exposes the scalar the panel hid."""
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        res = c.get("/api/memory/name")
        assert res.status_code in (200, 401)
        if res.status_code == 200:
            assert "name" in res.json()


def test_name_shared_across_chats(tmp_path, monkeypatch):
    """Tell the name in chat A, start a fresh chat B: the agent's prompt
    for B must already carry the name (stubbed LLM, real vault)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "name-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from types import SimpleNamespace
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore
    from backend.chatflow import archive_current, run_chat
    import agent as agent_mod
    from agent import runtime as rt_mod

    # Stub at the LLM boundary (established pattern in
    # test_degenerate_answer.py): the real memorize + prompt assembly in
    # runtime.answer_with_fallback still runs, so this proves the name
    # mined in chat A reaches the system prompt built for chat B.
    seen = {}

    def _invoke(llm, messages, budget=None, **kw):
        for m in messages:
            if m.__class__.__name__ == "SystemMessage":
                seen["system"] = str(getattr(m, "content", ""))
        return SimpleNamespace(content="Got it, thanks!")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    monkeypatch.setattr(rt_mod, "SYNTHESIS_TIERS", [("Fake", lambda: object())])
    monkeypatch.setattr(rt_mod, "FAST_TIERS", [("Fake", lambda: object())])

    ctx = UserContext(user_id="name-user", user_store=UserStore("name-user"),
                      file_store=FileStore("name-user"), limit_key="name-user",
                      source="env")
    run_chat(ctx, "i am mishel")  # chat A
    stored, _warnings = ctx.user_store.load_chats()
    record, fresh = archive_current(stored.get("current", []))
    ctx.user_store.save_chats([record] + stored.get("chats", []), fresh)
    run_chat(ctx, "whats my name?")  # chat B (fresh history)
    assert "User name: Mishel" in seen.get("system", ""), seen
