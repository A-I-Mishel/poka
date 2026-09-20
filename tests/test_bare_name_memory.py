"""Bare-name contextual mining tests (Fix 1).

A lone name ("mishel") is only meaningful directly after the assistant
asked for identity. Headed phrasings keep their existing behavior.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import memory as mem

ASK = "I don't have any information about your identity. Could you tell me more about yourself?"


def _mine(history, tmp_path):
    mem.set_memory_dir(str(tmp_path))
    try:
        res = mem.update_memory_incremental(history)
        return res, mem.load_structured_memory()
    finally:
        mem.set_memory_dir("")


def test_bare_name_after_identity_question(tmp_path):
    _res, stored = _mine([
        {"role": "assistant", "content": ASK},
        {"role": "user", "content": "mishel"},
    ], tmp_path)
    assert stored["user_name"] == "Mishel"
    names = [f for f in stored["facts"] if f.get("type") == "name"]
    assert len(names) == 1
    assert names[0]["confidence"] == "low"
    assert names[0]["source"] == "inferred"


def test_bare_name_without_question_stores_nothing(tmp_path):
    _res, stored = _mine([
        {"role": "user", "content": "mishel"},
    ], tmp_path)
    assert stored["user_name"] is None
    assert stored["facts"] == []


def test_bare_name_after_plain_statement_stores_nothing(tmp_path):
    _res, stored = _mine([
        {"role": "assistant", "content": "Hey there! How can I help today?"},
        {"role": "user", "content": "mishel"},
    ], tmp_path)
    assert stored["user_name"] is None
    assert stored["facts"] == []


def test_gap_turn_breaks_adjacency(tmp_path):
    _res, stored = _mine([
        {"role": "assistant", "content": ASK},
        {"role": "user", "content": "hmm, let me think"},
        {"role": "user", "content": "mishel"},
    ], tmp_path)
    assert stored["user_name"] is None
    assert [f for f in stored["facts"] if f.get("type") == "name"] == []


def test_guards_still_apply_after_question(tmp_path):
    for text in ("happy", "thank you very much indeed", "see you soon",
                 "ok", "123"):
        _res, stored = _mine([
            {"role": "assistant", "content": ASK},
            {"role": "user", "content": text},
        ], tmp_path)
        assert stored["user_name"] is None, text
        assert [f for f in stored["facts"] if f.get("type") == "name"] == [], text


def test_headed_phrasing_still_explicit(tmp_path):
    _res, stored = _mine([
        {"role": "user", "content": "my name is sam"},
    ], tmp_path)
    assert stored["user_name"] == "Sam"
    names = [f for f in stored["facts"] if f.get("type") == "name"]
    assert names and names[0]["confidence"] == "high"


def test_two_word_name_accepted(tmp_path):
    _res, stored = _mine([
        {"role": "assistant", "content": "What should I call you?"},
        {"role": "user", "content": "mary jane"},
    ], tmp_path)
    assert stored["user_name"] == "Mary Jane"


def test_two_chat_bare_name_shared(tmp_path, monkeypatch):
    """Bare name told in chat A (after the assistant asked) reaches the
    system prompt built for a fresh chat B (stubbed LLM boundary)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "barename-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from types import SimpleNamespace
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore
    from backend.chatflow import archive_current, run_chat
    import agent as agent_mod
    from agent import runtime as rt_mod

    seen = {}
    norm_calls = {"n": 0}

    def _invoke(llm, messages, budget=None, **kw):
        items = messages if isinstance(messages, list) else []
        contents = [str(getattr(m, "content", "")) for m in items]
        if any("Decide how a newly extracted" in c for c in contents):
            norm_calls["n"] += 1
            return SimpleNamespace(
                content="verdict: new\nkey: name: mishel\n"
                        "confidence: low\n"
                        "aliases: mishel, name\n")
        for m in items:
            if m.__class__.__name__ == "SystemMessage":
                seen["system"] = str(getattr(m, "content", ""))
        text = contents[-1] if contents else ""
        if "who am i" in text.lower():
            return SimpleNamespace(
                content="I don't know you yet. What should I call you?")
        return SimpleNamespace(content="Got it, thanks!")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    monkeypatch.setattr(rt_mod, "SYNTHESIS_TIERS", [("Fake", lambda: object())])

    ctx = UserContext(user_id="barename-user",
                      user_store=UserStore("barename-user"),
                      file_store=FileStore("barename-user"),
                      limit_key="barename-user", source="env")
    try:
        run_chat(ctx, "who am i")  # chat A turn 1: assistant asks identity
        run_chat(ctx, "mishel")    # chat A turn 2: bare-name reply
        stored, _warnings = ctx.user_store.load_chats()
        record, fresh = archive_current(stored.get("current", []))
        ctx.user_store.save_chats([record] + stored.get("chats", []), fresh)
        run_chat(ctx, "whats my name?")  # chat B (fresh history)

        assert norm_calls["n"] == 1
        assert "User name: Mishel" in seen.get("system", ""), seen
    finally:
        mem.set_memory_dir("")
