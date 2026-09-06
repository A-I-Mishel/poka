"""Multi-file attachment tests (Phase 4E-2).

pending_attachments is the canonical list; legacy pending_attach dicts
normalize into it and the first entry is mirrored back. Fresh uploads,
recent reuse, and camera append (cap 5 total, 3 images); removal,
send hints, edit-all, and retry preserve every ID.

Hermetic: tmp POKA_DATA_DIR + env identity. Agent stubbed.
"""

import io
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent  # noqa: F401  (keeps import order consistent with other UI tests)

# Bind the app's from-imports to the REAL service functions before any
# AppTest run (see the import-order note in test_force_search_flow.py).
import application.session as app_session  # noqa: F401
import services.auth  # noqa: F401
import ui.chat  # noqa: F401
import ui.components  # noqa: F401
import ui.composer  # noqa: F401
import ui.sidebar  # noqa: F401
import ui.uploads  # noqa: F401
from application.session import (
    _attachment_append,
    _pending_list,
    _set_pending_list,
)
from services.files import FileStore
from services.storage import UserStore, clean_messages
from ui.chat import _attachment_hint

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))

PDF_BYTES = b"%PDF-1.4\n%\n"
CSV_BYTES = b"a,b\n1,2\n3,4\n"


def _real_png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color="blue").save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _real_png_bytes()


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _clean_agent_state():
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()


@pytest.fixture()
def multi_env(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    return tmp_path / "data"


def _use_user(monkeypatch, name):
    monkeypatch.setenv("POKA_USER_ID", name)
    return str(UserStore(name).root)


def _entry(uid, kind="pdf", name="f.pdf", mark=None):
    return {"upload_id": uid, "kind": kind, "name": name,
            "path": name, "mark": mark or ["t", uid]}


def _run_app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.session_state.messages = []
    at.session_state.chats = []
    at.run(timeout=60)
    assert not at.exception
    return at


def _md(at):
    return " ".join(str(m.value) for m in at.markdown)


def _toasts(at):
    return " ".join(str(t.value) for t in at.toast)


def _stub_app_agent(monkeypatch, **extra):
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )
    payload = {"output": "ok", "active_tier": "T", "task_type": "simple"}
    payload.update(extra)
    captured = {}

    def fake_answer(user_input, chat_history=None, **kwargs):
        captured["input"] = user_input
        return dict(payload)

    monkeypatch.setattr(agent, "answer_with_fallback", fake_answer)
    return captured


def _open_menu(at):
    at.button(key="composer_plus").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["show_attach_menu"] is True
    return at


def _open_picker(at):
    at.button(key="menu-files").click().run(timeout=120)
    assert not at.exception
    return at


# -- pure state semantics --------------------------------------------------

def test_single_append_and_mirror():
    updated, error = _attachment_append([], _entry("a" * 16))
    assert error == "" and len(updated) == 1
    # legacy mirror keeps older readers working
    stored = _set_pending_list(updated)
    assert stored == updated


def test_two_appends_preserve_order():
    first, _ = _attachment_append([], _entry("a" * 16, "pdf", "a.pdf"))
    second, error = _attachment_append(first, _entry("b" * 16, "csv", "b.csv"))
    assert error == "" and [e["upload_id"] for e in second] == ["a" * 16, "b" * 16]


def test_maximum_enforced():
    existing = [_entry(str(i) * 16) for i in
                ["a", "b", "c", "d", "e"]]
    updated, error = _attachment_append(existing, _entry("f" * 16))
    assert len(updated) == 5 and [e["upload_id"] for e in updated] == [
        s * 16 for s in ["a", "b", "c", "d", "e"]]
    assert error == "At most 5 attachments per message."


def test_duplicate_id_idempotent():
    first, _ = _attachment_append([], _entry("a" * 16))
    second, error = _attachment_append(first, _entry("a" * 16, "csv", "other.csv"))
    assert error == "" and second == first


def test_invalid_entries_rejected():
    base, _ = _attachment_append([], _entry("a" * 16))
    for bad in [{"no": 1}, "x", None, {"upload_id": ""}]:
        updated, error = _attachment_append(base, bad)
        assert updated == base and error != ""


def test_image_cap():
    existing = []
    for i in ["a", "b", "c"]:
        existing, error = _attachment_append(
            existing, _entry(i * 16, "image", f"{i}.png"))
        assert error == ""
    updated, error = _attachment_append(
        existing, _entry("d" * 16, "image", "d.png"))
    assert len(updated) == 3
    assert error == "At most 3 images per message."
    mixed, error = _attachment_append(existing, _entry("e" * 16, "pdf", "e.pdf"))
    assert error == "" and len(mixed) == 4


def test_legacy_pending_normalizes():
    import streamlit as st

    # NOTE: bare st.session_state persists process-globally outside a
    # script run, so this test resets before and after itself.
    _set_pending_list([])
    try:
        assert _pending_list() == []
        st.session_state.pending_attach = dict(_entry("a" * 16))
        assert _pending_list() == [dict(_entry("a" * 16))]
    finally:
        _set_pending_list([])


def test_hint_single_byte_identical():
    entry = {"upload_id": "a" * 16, "kind": "pdf", "name": "r.pdf"}
    assert _attachment_hint(entry, 1, 1) == (
        "\n\n[Attached PDF 'r.pdf' with upload ID: "
        + "a" * 16
        + ". To read it, call read_pdf(upload_id=\""
        + "a" * 16
        + "\"). Never use any other path or ID.]"
    )


def test_hint_multi_numbered_deterministic():
    first = {"upload_id": "a" * 16, "kind": "pdf", "name": "a.pdf"}
    second = {"upload_id": "b" * 16, "kind": "csv", "name": "b.csv"}
    hint = _attachment_hint(first, 1, 2) + _attachment_hint(second, 2, 2)
    assert "[Attached PDF 1/2" in hint
    assert "[Attached CSV 2/2" in hint
    assert hint.count("a" * 16) == 2 and hint.count("b" * 16) == 2
    assert "uploads/" not in hint and "data/" not in hint


# -- AppTest flows -----------------------------------------------------------

def test_case_a_two_fresh_uploads_send(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-fresh")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    _open_picker(at)
    at.file_uploader(key="composer_file_uploader").set_value(
        ("a.pdf", PDF_BYTES, "application/pdf")).run(timeout=120)
    assert not at.exception
    at.file_uploader(key="composer_file_uploader").set_value(
        ("b.csv", CSV_BYTES, "text/csv")).run(timeout=120)
    assert not at.exception
    pending = at.session_state["pending_attachments"]
    assert [e["kind"] for e in pending] == ["pdf", "csv"]
    # legacy mirror intact
    assert at.session_state["pending_attach"]["upload_id"] == pending[0]["upload_id"]


def test_case_a_send_preserves_both_ids(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-send")
    captured = _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    _open_picker(at)
    at.file_uploader(key="composer_file_uploader").set_value(
        ("a.pdf", PDF_BYTES, "application/pdf")).run(timeout=120)
    at.file_uploader(key="composer_file_uploader").set_value(
        ("b.csv", CSV_BYTES, "text/csv")).run(timeout=120)
    at.text_input(key="composer_input_0").set_value("compare").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    user_msg = [m for m in at.session_state.messages if m["role"] == "user"][0]
    assert user_msg["content"] == "compare"  # user text clean, no IDs
    assert len(user_msg["attachments"]) == 2
    ids = [a["id"] for a in user_msg["attachments"]]
    assert f'upload_id="{ids[0]}"' in captured["input"]
    assert f'upload_id="{ids[1]}"' in captured["input"]
    assert "[Attached PDF 1/2" in captured["input"]
    assert "[Attached CSV 2/2" in captured["input"]


def test_case_b_fresh_plus_recent(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-mix")
    seeded = FileStore("multi-mix").save_upload(CSV_BYTES, "old.csv")
    captured = _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.pending_attach = {
        "upload_id": "f" * 16, "kind": "pdf", "name": "fresh.pdf",
        "path": "fresh.pdf", "mark": ["menu", "fresh.pdf", 10],
    }
    at.run(timeout=60)
    _open_menu(at)
    at.button(key=f"recent-csv-{seeded.id}").click().run(timeout=120)
    assert not at.exception
    pending = at.session_state["pending_attachments"]
    assert [e["upload_id"] for e in pending] == ["f" * 16, seeded.id]
    at.text_input(key="composer_input_0").set_value("both").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    user_msg = [m for m in at.session_state.messages if m["role"] == "user"][0]
    assert [a["id"] for a in user_msg["attachments"]] == ["f" * 16, seeded.id]
    assert f'upload_id="{seeded.id}"' in captured["input"]


def test_case_c_limit_and_reject(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-cap")
    ids = [FileStore("multi-cap").save_upload(PDF_BYTES, f"f{i}.pdf").id
           for i in range(5)]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    # Menu lists newest first; select all five visible rows.
    for uid in reversed(ids):
        at.button(key=f"recent-pdf-{uid}").click().run(timeout=120)
        assert not at.exception
    assert len(at.session_state["pending_attachments"]) == 5
    # A sixth file via the fresh-upload picker is rejected with feedback.
    at.button(key="menu-files").click().run(timeout=120)
    assert not at.exception
    at.file_uploader(key="composer_file_uploader").set_value(
        ("extra.pdf", PDF_BYTES, "application/pdf")).run(timeout=120)
    assert not at.exception
    assert len(at.session_state["pending_attachments"]) == 5
    assert "At most 5 attachments" in _toasts(at)
    assert at.session_state["show_attach_menu"] is True


def test_case_d_remove_middle(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-rm")
    ids = [FileStore("multi-rm").save_upload(PDF_BYTES, f"f{i}.pdf").id
           for i in range(3)]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    for uid in ids:
        at.button(key=f"recent-pdf-{uid}").click().run(timeout=120)
    assert not at.exception
    at.button(key=f"rm-attach-{ids[1]}").click().run(timeout=120)
    assert not at.exception
    remaining = [e["upload_id"] for e in at.session_state["pending_attachments"]]
    assert remaining == [ids[0], ids[2]]
    assert at.session_state["pending_attach"]["upload_id"] == ids[0]
    body = _md(at)
    assert f"f0.pdf" in body and f"f2.pdf" in body


def test_case_e_edit_restores_all(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-edit")
    first = FileStore("multi-edit").save_upload(PDF_BYTES, "a.pdf")
    second = FileStore("multi-edit").save_upload(CSV_BYTES, "b.csv")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = [
        {"role": "user", "content": "compare",
         "attachments": [{"id": first.id, "kind": "pdf", "name": "a.pdf"},
                         {"id": second.id, "kind": "csv", "name": "b.csv"}]},
        {"role": "assistant", "content": "done"},
    ]
    at.run(timeout=120)
    at.button(key="edit-0").click().run(timeout=120)
    assert not at.exception, f"edit failed: {at.exception}"
    restored = at.session_state["pending_attachments"]
    assert [(e["upload_id"], e["kind"]) for e in restored] == [
        (first.id, "pdf"), (second.id, "csv")]
    assert at.session_state.messages == []


def test_case_f_foreign_absent(multi_env, monkeypatch):
    FileStore("multi-alice").save_upload(PDF_BYTES, "alice.pdf")
    alice_id = FileStore("multi-alice").list_uploads()[0].id
    _use_user(monkeypatch, "multi-bob")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    with pytest.raises(KeyError):
        at.button(key=f"recent-pdf-{alice_id}")
    assert FileStore("multi-bob").list_uploads() == []


def test_case_g_chips_all_present(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-chips")
    ids = [FileStore("multi-chips").save_upload(PDF_BYTES, f"doc{i}.pdf").id
           for i in range(5)]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    for uid in ids:
        at.button(key=f"recent-pdf-{uid}").click().run(timeout=120)
    assert not at.exception
    body = _md(at)
    for i in range(5):
        assert f"doc{i}.pdf" in body
        at.button(key=f"rm-attach-{ids[i]}")


def test_retry_preserves_multi(multi_env, monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )
    calls = {"n": 0}

    def flaky(user_input, chat_history=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"output": "recovered", "active_tier": "T", "task_type": "simple"}

    monkeypatch.setattr(agent, "answer_with_fallback", flaky)
    _use_user(monkeypatch, "multi-retry")
    first = FileStore("multi-retry").save_upload(PDF_BYTES, "a.pdf")
    second = FileStore("multi-retry").save_upload(CSV_BYTES, "b.csv")
    at = _run_app()
    _open_menu(at)
    at.button(key=f"recent-pdf-{first.id}").click().run(timeout=120)
    at.button(key=f"recent-csv-{second.id}").click().run(timeout=120)
    at.text_input(key="composer_input_0").set_value("go").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assert f'upload_id="{first.id}"' in at.session_state["last_failed"]
    assert f'upload_id="{second.id}"' in at.session_state["last_failed"]
    at.button(key="retry-main").click().run(timeout=120)
    assert not at.exception, f"retry failed: {at.exception}"
    assistant = [m for m in at.session_state.messages if m["role"] == "assistant"]
    assert len(assistant) == 1 and assistant[0]["content"] == "recovered"


def test_images_multi_allowed_fourth_rejected(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-img")
    ids = [FileStore("multi-img").save_upload(PNG_BYTES, f"p{i}.png").id
           for i in range(4)]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    for uid in ids[:3]:
        at.button(key=f"recent-img-{uid}").click().run(timeout=120)
        assert not at.exception
    assert len(at.session_state["pending_attachments"]) == 3
    at.button(key=f"recent-img-{ids[3]}").click().run(timeout=120)
    assert not at.exception
    assert len(at.session_state["pending_attachments"]) == 3
    assert "At most 3 images" in _toasts(at)


def test_two_images_send_and_render(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-2img")
    first = FileStore("multi-2img").save_upload(PNG_BYTES, "one.png")
    second = FileStore("multi-2img").save_upload(PNG_BYTES, "two.png")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    at.button(key=f"recent-img-{first.id}").click().run(timeout=120)
    at.button(key=f"recent-img-{second.id}").click().run(timeout=120)
    at.text_input(key="composer_input_0").set_value("compare pics").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    user_msg = [m for m in at.session_state.messages if m["role"] == "user"][0]
    assert [a["id"] for a in user_msg["attachments"]] == [first.id, second.id]
    assert "image" in user_msg  # first-image legacy path intact
    at.run(timeout=60)
    assert not at.exception  # history re-renders both images


def test_search_toggle_still_works(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-search")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    at.button(key="menu-search").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["force_search"] is True


def test_legacy_pending_dict_still_sends(multi_env, monkeypatch):
    _use_user(monkeypatch, "multi-legacy")
    seeded = FileStore("multi-legacy").save_upload(PDF_BYTES, "old.pdf")
    captured = _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.pending_attach = {
        "upload_id": seeded.id, "kind": "pdf", "name": "old.pdf",
        "path": "old.pdf", "mark": ["menu", "old.pdf", 10],
    }
    at.run(timeout=60)
    assert "old.pdf" in _md(at)  # chip renders from legacy shape
    at.text_input(key="composer_input_0").set_value("read").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    user_msg = [m for m in at.session_state.messages if m["role"] == "user"][0]
    assert user_msg["attachments"] == [{"id": seeded.id, "kind": "pdf",
                                        "name": "old.pdf"}]
    assert f'upload_id="{seeded.id}"' in captured["input"]


def test_pruning_sees_all_ids(multi_env):
    store = FileStore("multi-prune")
    used_a = store.save_upload(PDF_BYTES, "a.pdf")
    used_b = store.save_upload(PDF_BYTES, "b.pdf")
    free = store.save_upload(PDF_BYTES, "c.pdf")
    for meta in (used_a, used_b, free):
        reg = json.loads(store.uploads_registry.read_text(encoding="utf-8"))
        reg[meta.id]["created"] = time.time() - 9 * 86400
        store.uploads_registry.write_text(json.dumps(reg), encoding="utf-8")
    msgs = [{"role": "user", "content": "x",
             "attachments": [{"id": used_a.id, "kind": "pdf", "name": "a.pdf"},
                             {"id": used_b.id, "kind": "pdf", "name": "b.pdf"}]}]
    UserStore("multi-prune").save_chats([], msgs)
    # Same referenced-ID scan ensure_session_defaults performs.
    referenced = set()
    for m in msgs:
        for a in (m.get("attachments", []) or []):
            if isinstance(a, dict) and a.get("id"):
                referenced.add(str(a["id"]))
    assert store.prune_stale_uploads(7, referenced) == 1
    assert store.get_upload(used_a.id) is not None
    assert store.get_upload(used_b.id) is not None
    assert store.get_upload(free.id) is None
