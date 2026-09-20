"""Teaching resilience (Phase E): thin windows + double-tap guard.

1. A title-only window (diagrams/scanned pages: titles extract, bodies
   live in images) must direct the model to read_pdf_page first — never
   bounce the user to re-upload on the first pass.
2. An identical message re-sent while its first turn is still generating
   (client abort + retry) must short-circuit instead of launching a
   second full turn (double quota burn + duplicate answers).
"""

import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _ctx(tmp_path, monkeypatch, uid="teach-res-user"):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", uid)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore

    return UserContext(user_id=uid, user_store=UserStore(uid),
                       file_store=FileStore(uid), limit_key=uid, source="env")


def test_thin_pdf_window_points_at_read_pdf_page(tmp_path, monkeypatch):
    from backend import teach as teach_mod

    ctx = _ctx(tmp_path, monkeypatch)
    attach = {"kind": "pdf", "id": "abc123", "name": "Lecture.pdf"}
    thin = [(4, "What is a Graph?"), (5, "Directed vs. undirected graphs"),
            (6, "Weighted graphs")]

    monkeypatch.setattr(
        teach_mod, "_extract_teaching_blocks", lambda c, a: (thin, 138, "OK"))
    hint, start, end, total, status = teach_mod._teaching_window_hint(ctx, attach, 3)
    assert status == "OK"
    assert (start, end, total) == (4, 6, 138)
    assert "read_pdf_page" in hint
    assert "abc123" in hint
    assert "re-upload" in hint  # last resort only


def test_thick_window_has_no_ocr_note(tmp_path, monkeypatch):
    from backend import teach as teach_mod

    ctx = _ctx(tmp_path, monkeypatch)
    attach = {"kind": "pdf", "id": "abc123", "name": "Lecture.pdf"}
    thick = [(1, "A graph is a pair (V, E) of vertices and edges. " * 10),
             (2, "Breadth-first search explores level by level. " * 10)]

    monkeypatch.setattr(
        teach_mod, "_extract_teaching_blocks", lambda c, a: (thick, 2, "OK"))
    hint, start, end, total, status = teach_mod._teaching_window_hint(ctx, attach, 0)
    assert status == "OK"
    assert "read_pdf_page" not in hint


def test_thin_document_window_teaches_generally(tmp_path, monkeypatch):
    from backend import teach as teach_mod

    ctx = _ctx(tmp_path, monkeypatch)
    attach = {"kind": "document", "id": "abc123", "name": "Deck.pptx"}
    thin = [(4, "What is a Graph?")]

    monkeypatch.setattr(
        teach_mod, "_extract_teaching_blocks", lambda c, a: (thin, 10, "OK"))
    hint, start, end, total, status = teach_mod._teaching_window_hint(ctx, attach, 3)
    assert status == "OK"
    assert "read_pdf_page" not in hint  # no per-slide reader for pptx
    assert "general" in hint


def test_inflight_claim_release_and_ttl():
    from backend.flow import turns as turns_mod

    key = ("chat-path", "hello")
    turns_mod._INFLIGHT_TURNS.clear()
    assert turns_mod._claim_inflight(key) is True
    assert turns_mod._claim_inflight(key) is False  # live duplicate
    assert turns_mod._claim_inflight(("chat-path", "other")) is True
    turns_mod._release_inflight(("chat-path", "other"))
    # Crashed turns expire via TTL instead of wedging the chat.
    turns_mod._INFLIGHT_TURNS[key] = time.time() - 400.0
    assert turns_mod._claim_inflight(key) is True
    turns_mod._INFLIGHT_TURNS.clear()


def test_identical_resend_short_circuits_while_running(monkeypatch):
    from backend.flow import turns as turns_mod

    turns_mod._INFLIGHT_TURNS.clear()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def _blocking_inner(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(timeout=10)
        return {"message": {"role": "assistant", "content": "done"},
                "active_tier": "T", "task_type": "simple", "warnings": [],
                "fallback": None, "pending_approvals": [],
                "corrections": []}

    monkeypatch.setattr(turns_mod, "_run_chat_inner", _blocking_inner)
    monkeypatch.setattr(turns_mod, "_append_turn_atomic",
                        lambda store, *msgs: None)
    store = types.SimpleNamespace(chats_path="chat-1")
    ctx = types.SimpleNamespace(user_id="u", user_store=store,
                                limit_key="u", source="env")

    t = threading.Thread(target=lambda: turns_mod.run_chat(ctx, "teach me slides"))
    t.start()
    assert entered.wait(timeout=10)
    try:
        dupe = turns_mod.run_chat(ctx, "  TEACH me slides  ")
        assert dupe["active_tier"] == "clarify"
        assert "still generating" in dupe["message"]["content"]
        assert dupe["corrections"] == []
        # Different text still proceeds (inner called once so far).
        assert len(calls) == 1
    finally:
        release.set()
        t.join(timeout=10)
    assert len(calls) == 1
    # After completion the same text works again.
    again = turns_mod.run_chat(ctx, "teach me slides")
    assert again["message"]["content"] == "done"
    assert len(calls) == 2
    turns_mod._INFLIGHT_TURNS.clear()
