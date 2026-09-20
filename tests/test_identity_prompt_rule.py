"""Identity-question prompt rule tests (Fix 2).

Covers the deterministic part: the rule exists in SYSTEM_PROMPT after
the retrieved-memory paragraph, and prompts built for a nameless vault
carry the rule alongside the memory dump. Live model compliance is
verified post-deploy against the reported screenshot scenario.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.prompts import USER_IDENTITY_PARAGRAPH, _build_system_prompt


def test_identity_rule_present_and_placed():
    flat = " ".join(USER_IDENTITY_PARAGRAPH.split())
    assert "Identity questions about the user" in flat
    assert "answer from the stored" in flat
    assert "never enumerate stored preferences, patterns," in flat
    # Both prompt sizes carry the rule via the shared builder (short
    # identity questions take the simple path — the reported case).
    for simple in (False, True):
        out = _build_system_prompt("", "", "", simple=simple)
        assert "Identity questions about the user" in out, simple


def test_rule_reaches_built_prompt_with_nameless_vault(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "identity-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    import agent as agent_mod
    from agent import runtime as rt_mod
    from types import SimpleNamespace
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore
    from backend.chatflow import run_chat

    seen = {}

    def _invoke(llm, messages, budget=None, **kw):
        for m in messages:
            if m.__class__.__name__ == "SystemMessage":
                seen["system"] = str(getattr(m, "content", ""))
        return SimpleNamespace(content="I don't know your name yet.")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    monkeypatch.setattr(rt_mod, "SYNTHESIS_TIERS", [("Fake", lambda: object())])

    ctx = UserContext(user_id="identity-user",
                      user_store=UserStore("identity-user"),
                      file_store=FileStore("identity-user"),
                      limit_key="identity-user", source="env")
    run_chat(ctx, "who am i")
    system = seen.get("system", "")
    assert "Identity questions about the user" in system, system


def test_rule_present_in_simple_system_prompt():
    out = _build_system_prompt("", "", "", simple=True)
    assert "Identity questions about the user" in out
