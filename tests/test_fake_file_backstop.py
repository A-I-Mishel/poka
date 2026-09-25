"""Fake-file backstop + teaching-hint flag (screenshot regressions).

A weak tier asked for a file deliverable pasted a fake truncated
base64 blob with decode instructions and a phantom attachment instead
of using a file tool. The answer path now serves the honest Export
pointer instead of persisting the fabrication. Separately, the "Say
Next" hint renders only on genuine teaching turns (persisted flag),
never on messages merely quoting a lesson.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.flow import turns as turns_mod
from backend.flow.stages import _FAKE_FILE_FALLBACK, _is_fabricated_file


@pytest.fixture()
def _user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "fake-file-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from services import memory as mem
    from services.files import FileStore
    from services.storage import UserStore

    mem.set_memory_dir("")
    ctx = UserContext(user_id="fake-file-user",
                      user_store=UserStore("fake-file-user"),
                      file_store=FileStore("fake-file-user"),
                      limit_key="fake-file-user", source="env")
    try:
        yield ctx
    finally:
        mem.set_memory_dir("")


_FAKE = """Here is your PDF.

JVBERi0xLjQKJaqrrK0KNCAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwo
vUGFnZXMgNSAwIFIKPj4KZW5kb2JqCjUgMCBvYmoKPDwvVHlwZSAv
[TRUNCATED FOR BREVITY - the full string is in the attachment below]

Decode it: echo "<PASTE>" | base64 -d > conversation.pdf
(The full base64 string is included in the attachment section.)
"""


def test_detector_needs_all_three_markers():
    assert _is_fabricated_file(_FAKE) is True
    assert _is_fabricated_file("short") is False
    # Real code answers with base64 but no truncation/attachment talk.
    assert _is_fabricated_file(
        "Here is a base64 example:\n" + "QUJD" * 100
        + "\ndecode it with any online decoder.") is False
    # A real download ID exempts the turn entirely.
    assert _is_fabricated_file(
        _FAKE + "\nSaved (file ID: a3b5ecfce1df4287)") is False


def test_fake_file_serves_honest_fallback(_user, monkeypatch):
    import agent as agent_mod
    from types import SimpleNamespace

    calls = []

    def _answer(*a, **k):
        calls.append(1)
        return SimpleNamespace(content=_FAKE, tool_calls=[])

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _answer)
    out = turns_mod.run_chat(_user, "convert the whole conversation into a pdf")
    assert out["message"]["content"] == _FAKE_FILE_FALLBACK
    assert "Export PDF" in out["message"]["content"]
    stored, _warnings = _user.user_store.load_chats()
    current = stored.get("current", [])
    assert current[-1]["content"] == _FAKE_FILE_FALLBACK


def test_quoting_turn_stamped_inactive(_user, monkeypatch):
    import agent as agent_mod
    from types import SimpleNamespace

    def _answer(*a, **k):
        return SimpleNamespace(
            content="As taught before:\n📘 FILE: Deck.pptx\nSlides: 1-1\nintro",
            tool_calls=[])

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _answer)
    out = turns_mod.run_chat(_user, "summarize what we covered")
    assert out["message"].get("teaching", {}).get("active") is False
    stored, _warnings = _user.user_store.load_chats()
    current = stored.get("current", [])
    assert current[-1].get("teaching", {}).get("active") is False


def test_cleaner_keeps_inactive_flag(tmp_path):
    from services.storage.cleaners import clean_messages

    msgs = [{"role": "assistant", "content": "x 📘 FILE: D\nSlides: 1-1",
             "teaching": {"active": False}}]
    out = clean_messages(msgs)
    assert out[-1].get("teaching") == {"active": False, "file": "", "cursor": 0}
