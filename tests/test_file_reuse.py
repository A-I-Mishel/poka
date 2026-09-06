"""Recent file reuse regression tests (Phase 4E-1).

Reattaching an owned upload must reuse its canonical ID with no copy,
no re-upload, and no ownership bypass. Single attachment only.

Hermetic: tmp POKA_DATA_DIR + env identity (deterministic vault, zero
repo pollution). Agent stubbed; no live providers.
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent  # noqa: F401  (keeps import order consistent with other UI tests)

# Bind the app's from-imports to the REAL service functions before any
# AppTest run (see the import-order note in test_force_search_flow.py).
import application.session  # noqa: F401
import services.auth  # noqa: F401
import ui.chat  # noqa: F401
import ui.components  # noqa: F401
import ui.composer  # noqa: F401
import ui.sidebar  # noqa: F401
import ui.uploads  # noqa: F401
from services.files import FileStore
from services.storage import UserStore
from ui.uploads import _recent_kind_label, _recent_tag

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))

PDF_BYTES = b"%PDF-1.4\n%\n"
CSV_BYTES = b"a,b\n1,2\n3,4\n"


def _real_png_bytes() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color="red").save(buf, format="PNG")
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
def reuse_env(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    return tmp_path / "data"


def _use_user(monkeypatch, name):
    monkeypatch.setenv("POKA_USER_ID", name)
    return str(UserStore(name).root)


def _backdate_upload(user, upload_id, days_old):
    store = FileStore(user)
    reg = json.loads(store.uploads_registry.read_text(encoding="utf-8"))
    reg[upload_id]["created"] = time.time() - days_old * 86400
    store.uploads_registry.write_text(json.dumps(reg), encoding="utf-8")


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


# -- registry: list, order, labels ---------------------------------------

def test_recent_uploads_newest_first(reuse_env):
    store = FileStore("reuse-user")
    first = store.save_upload(PDF_BYTES, "a.pdf")
    second = store.save_upload(CSV_BYTES, "b.csv")
    third = store.save_upload(PNG_BYTES, "c.png")
    _backdate_upload("reuse-user", second.id, 2)
    _backdate_upload("reuse-user", first.id, 9)
    ids = [m.id for m in store.list_uploads()]
    assert ids == [third.id, second.id, first.id]


def test_kind_labels_and_tags():
    assert _recent_kind_label("pdf") == "PDF"
    assert _recent_kind_label("csv") == "CSV"
    assert _recent_kind_label("image") == "Image"
    assert _recent_kind_label("weird") == "Image"
    assert _recent_tag("pdf") == "pdf"
    assert _recent_tag("csv") == "csv"
    assert _recent_tag("image") == "img"
    assert _recent_tag("weird") == "img"


def test_filenames_preserved(reuse_env):
    store = FileStore("reuse-user")
    long_name = "quarterly financial report draft v2 FINAL.pdf"
    meta = store.save_upload(PDF_BYTES, long_name)
    # sanitize_filename maps spaces to underscores (existing behavior).
    assert meta.display_name == "quarterly_financial_report_draft_v2_FINAL.pdf"
    assert meta.kind == "pdf"


# -- ownership: refusal paths --------------------------------------------

def test_foreign_id_refused(reuse_env):
    FileStore("reuse-alice").save_upload(PDF_BYTES, "alice.pdf")
    alice_id = FileStore("reuse-alice").list_uploads()[0].id
    assert FileStore("reuse-bob").get_upload(alice_id) is None
    assert FileStore("reuse-bob").resolve_upload(alice_id) is None


def test_invalid_ids_refused(reuse_env):
    store = FileStore("reuse-user")
    for bad in ["", "nope", "../x", " guess", None, 123,
                "ABCDEF1234567890", "a" * 15, "g" * 16]:
        assert store.get_upload(bad) is None, bad
        assert store.resolve_upload(bad) is None, bad


def test_missing_file_resolves_none(reuse_env):
    store = FileStore("reuse-user")
    meta = store.save_upload(PDF_BYTES, "gone.pdf")
    assert store.resolve_upload(meta.id) is not None
    (store.uploads_dir / meta.stored_name).unlink()
    assert store.get_upload(meta.id) is not None  # registry truthful
    assert store.resolve_upload(meta.id) is None  # bytes gone


# -- pruning ---------------------------------------------------------------

def test_pruning_protects_referenced(reuse_env):
    store = FileStore("reuse-user")
    old_used = store.save_upload(PDF_BYTES, "used.pdf")
    old_free = store.save_upload(PDF_BYTES, "free.pdf")
    _backdate_upload("reuse-user", old_used.id, 9)
    _backdate_upload("reuse-user", old_free.id, 9)
    removed = store.prune_stale_uploads(7, {old_used.id})
    assert removed == 1
    assert store.get_upload(old_used.id) is not None
    assert store.get_upload(old_free.id) is None


# -- images + separation -----------------------------------------------------

def test_reused_image_resolves(reuse_env):
    store = FileStore("reuse-user")
    meta = store.save_upload(PNG_BYTES, "photo.png")
    assert meta.kind == "image"
    assert store.resolve_upload(meta.id) is not None


def test_uploads_and_outputs_separate(reuse_env):
    store = FileStore("reuse-user")
    store.save_upload(PDF_BYTES, "in.pdf")
    store.register_output("out.pptx", b"PK\x03\x04x", "pptx")
    assert [(m.display_name, m.kind) for m in store.list_uploads()] == [
        ("in.pdf", "pdf")]
    assert [(m.display_name, m.kind) for m in store.list_outputs()] == [
        ("out.pptx", "pptx")]


# -- AppTest: select, chip, send ----------------------------------------------

def test_case_a_reuse_pdf_chip_and_send(reuse_env, monkeypatch):
    _use_user(monkeypatch, "reuse-pdf")
    seeded = FileStore("reuse-pdf").save_upload(PDF_BYTES, "research.pdf")
    before = FileStore("reuse-pdf").list_uploads()
    before_bytes = (FileStore("reuse-pdf").uploads_dir
                    / seeded.stored_name).read_bytes()
    captured = _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    at.button(key=f"recent-pdf-{seeded.id}").click().run(timeout=120)
    assert not at.exception
    pending = at.session_state["pending_attach"]
    assert pending["upload_id"] == seeded.id
    assert pending["kind"] == "pdf"
    assert pending["name"] == "research.pdf"
    # Menu stays open for multi-select (Phase 4E-2 behavior).
    assert at.session_state["show_attach_menu"] is True
    assert "research.pdf" in _md(at)
    # no duplicate storage: same registry entry, same bytes
    assert [m.id for m in FileStore("reuse-pdf").list_uploads()] == [
        m.id for m in before]
    assert (FileStore("reuse-pdf").uploads_dir
            / seeded.stored_name).read_bytes() == before_bytes
    at.text_input(key="composer_input_0").set_value("summarize").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    user_msg = [m for m in at.session_state.messages if m["role"] == "user"][0]
    assert user_msg["attachments"] == [{"id": seeded.id, "kind": "pdf",
                                        "name": "research.pdf"}]
    assert f'upload_id="{seeded.id}"' in captured["input"]


def test_case_b_reuse_csv_send(reuse_env, monkeypatch):
    _use_user(monkeypatch, "reuse-csv")
    seeded = FileStore("reuse-csv").save_upload(CSV_BYTES, "sales.csv")
    captured = _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    at.button(key=f"recent-csv-{seeded.id}").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["pending_attach"]["kind"] == "csv"
    at.text_input(key="composer_input_0").set_value("analyze").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assert "analyze_csv" in captured["input"]


def test_reuse_image_send(reuse_env, monkeypatch):
    _use_user(monkeypatch, "reuse-img")
    seeded = FileStore("reuse-img").save_upload(PNG_BYTES, "photo.png")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    at.button(key=f"recent-img-{seeded.id}").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["pending_attach"]["kind"] == "image"
    at.text_input(key="composer_input_0").set_value("describe").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    user_msg = [m for m in at.session_state.messages if m["role"] == "user"][0]
    assert user_msg["attachments"] == [{"id": seeded.id, "kind": "image",
                                        "name": "photo.png"}]


def test_selected_row_marked(reuse_env, monkeypatch):
    _use_user(monkeypatch, "reuse-mark")
    seeded = FileStore("reuse-mark").save_upload(PDF_BYTES, "m.pdf")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    assert not at.button(key=f"recent-pdf-{seeded.id}").label.startswith("✓")
    at.button(key=f"recent-pdf-{seeded.id}").click().run(timeout=120)
    # Menu stays open after selection; the row now shows selected.
    assert at.session_state["show_attach_menu"] is True
    assert at.button(key=f"recent-pdf-{seeded.id}").label.startswith("✓")


def test_case_c_foreign_file_absent(reuse_env, monkeypatch):
    FileStore("reuse-alice").save_upload(PDF_BYTES, "alice.pdf")
    alice_id = FileStore("reuse-alice").list_uploads()[0].id
    _use_user(monkeypatch, "reuse-bob")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    body = _md(at)
    assert "alice.pdf" not in body
    with pytest.raises(KeyError):
        at.button(key=f"recent-pdf-{alice_id}")
    assert "No uploaded files yet" in body


def test_case_d_pruned_file_omitted(reuse_env, monkeypatch):
    _use_user(monkeypatch, "reuse-pruned")
    seeded = FileStore("reuse-pruned").save_upload(PDF_BYTES, "gone.pdf")
    (FileStore("reuse-pruned").uploads_dir / seeded.stored_name).unlink()
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    # Broken rows never appear as selectable menu entries; the menu works.
    with pytest.raises(KeyError):
        at.button(key=f"recent-pdf-{seeded.id}")


def test_menu_empty_state(reuse_env, monkeypatch):
    _use_user(monkeypatch, "reuse-new")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    assert "No uploaded files yet" in _md(at)


def test_menu_cap_and_overflow(reuse_env, monkeypatch):
    _use_user(monkeypatch, "reuse-many")
    for i in range(7):
        FileStore("reuse-many").save_upload(PDF_BYTES, f"f{i}.pdf")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    metas = FileStore("reuse-many").list_uploads()
    for meta in metas[:5]:
        at.button(key=f"recent-pdf-{meta.id}")
    with pytest.raises(KeyError):
        at.button(key=f"recent-pdf-{metas[5].id}")
    assert "+2 more files" in _md(at)


# -- edit / metadata / memory ---------------------------------------------------

def test_edit_restores_reused_attachment(reuse_env, monkeypatch):
    _use_user(monkeypatch, "reuse-edit")
    seeded = FileStore("reuse-edit").save_upload(PDF_BYTES, "doc.pdf")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = [
        {"role": "user", "content": "read this",
         "attachments": [{"id": seeded.id, "kind": "pdf",
                          "name": "doc.pdf"}]},
    ]
    at.run(timeout=120)
    at.button(key="edit-0").click().run(timeout=120)
    assert not at.exception, f"edit failed: {at.exception}"
    pending = at.session_state["pending_attach"]
    assert pending["upload_id"] == seeded.id
    assert pending["kind"] == "pdf"


def test_metadata_intact_after_reuse_send(reuse_env, monkeypatch):
    _use_user(monkeypatch, "reuse-meta")
    seeded = FileStore("reuse-meta").save_upload(PDF_BYTES, "r.pdf")
    _stub_app_agent(monkeypatch, active_tier="Gemini 3.6 Flash",
                    task_type="research", tools_used=["read_pdf"])
    at = _run_app()
    _open_menu(at)
    at.button(key=f"recent-pdf-{seeded.id}").click().run(timeout=120)
    at.text_input(key="composer_input_0").set_value("summarize").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["model"] == "Gemini 3.6 Flash"
    assert meta["mode"] == "fast"
    assert meta["searched"] is False
    assert meta["tools"] == ["read_pdf"]


def test_memory_untouched_by_reuse(reuse_env, monkeypatch):
    from services import memory as mem_mod

    root = _use_user(monkeypatch, "reuse-mem")
    mem_mod.set_memory_dir(root)
    mem_mod.save_structured_memory({
        "preferences": {}, "past_tasks": [], "user_name": None,
        "facts": [{"type": "preference", "value": "Tea",
                   "polarity": "positive", "confidence": "high",
                   "source": "explicit", "date": "2026-01-01T00:00:00+00:00"}],
    })
    UserStore("reuse-mem").save_notes("NOTE-XYZ")
    FileStore("reuse-mem").save_upload(PDF_BYTES, "r.pdf")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    _open_menu(at)
    metas = FileStore("reuse-mem").list_uploads()
    at.button(key=f"recent-pdf-{metas[0].id}").click().run(timeout=120)
    at.text_input(key="composer_input_0").set_value("summarize").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    mem_mod.set_memory_dir(root)
    assert [f["value"] for f in mem_mod.list_memory_facts()] == ["Tea"]
    assert UserStore("reuse-mem").load_notes() == "NOTE-XYZ"
