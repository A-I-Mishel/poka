"""Artifact workspace regression tests (Phase 4D).

Generated outputs become first-class linked artifacts: {id,kind,name}
on assistant messages (explicit ID-diff linkage, no heuristics),
in-chat rows, and a sidebar gallery. Uploads and outputs stay separate.

Hermetic: tmp POKA_DATA_DIR + env identity for AppTest (deterministic
vault, zero repo pollution); direct FileStore use for unit tests.
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
from services.storage import UserStore, clean_messages
from services.storage import StorageError
from ui.components import (
    _artifact_card_html,
    _artifact_kind_label,
    _format_bytes,
    _rel_date,
)

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))

DOCX_BYTES = b"PK\x03\x04fake-docx-bytes"


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
def art_env(tmp_path, monkeypatch):
    """Hermetic vault dir; caller picks the user id via _use_user."""
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    return tmp_path / "data"


def _use_user(monkeypatch, name):
    monkeypatch.setenv("POKA_USER_ID", name)
    return str(UserStore(name).root)


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


def _dl_keys(at):
    return [str(b.key) for b in at.download_button]


def _stub_app_agent(monkeypatch, register=(), **extra):
    """Stub the agent; optionally register outputs mid-call like tools do."""
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )
    payload = {"output": "ok", "active_tier": "T", "task_type": "simple"}
    payload.update(extra)
    made = []

    def fake_answer(user_input, chat_history=None, **kwargs):
        from services.context import get_current_user_id

        for display_name, kind in register:
            meta = FileStore(get_current_user_id()).register_output(
                display_name, DOCX_BYTES, kind)
            made.append(meta)
        return dict(payload)

    monkeypatch.setattr(agent, "answer_with_fallback", fake_answer)
    return made


# -- registration + metadata model -------------------------------------

def test_artifact_registration(art_env):
    store = FileStore("art-user")
    meta = store.register_output("Brief.pptx", b"PK\x03\x04x", "pptx")
    assert len(meta.id) == 16 and meta.kind == "pptx"
    assert meta.display_name == "Brief.pptx"
    assert meta.size == 5
    weird = store.register_output("weird.xyz", b"data", "weird-kind")
    assert weird.kind == "file"
    # Distinct timestamps: created uses wall-clock time, which can tie
    # at timer granularity and make newest-first ordering nondeterministic.
    reg = json.loads(store.outputs_registry.read_text(encoding="utf-8"))
    reg[meta.id]["created"] -= 10
    store.outputs_registry.write_text(json.dumps(reg), encoding="utf-8")
    assert [m.id for m in store.list_outputs()] == [weird.id, meta.id]


def test_artifacts_round_trip_with_metadata(art_env):
    msgs = [{"role": "assistant", "content": "done", "model": "T",
             "mode": "fast", "searched": False,
             "artifacts": [{"id": "a" * 16, "kind": "pptx",
                            "name": "Brief.pptx"},
                           {"id": "b" * 16, "kind": "docx",
                            "name": "Doc.docx"}]}]
    UserStore("art-user").save_chats([], msgs)
    loaded, warnings = UserStore("art-user").load_chats()
    assert warnings == []
    got = loaded["current"][0]
    assert got["artifacts"] == msgs[0]["artifacts"]
    assert got["model"] == "T" and got["mode"] == "fast"


def test_cleaner_artifact_policy():
    msgs = [{"role": "assistant", "content": "x",
             "artifacts": [{"id": "a" * 16, "kind": "pptx", "name": "B.pptx"},
                           {"id": "", "kind": "pptx", "name": "n"},
                           {"id": "c" * 16, "kind": "pdf", "name": "n"},
                           {"id": "d" * 16, "kind": "docx"},
                           {"id": "e" * 16, "kind": "docx", "name": 5},
                           "junk",
                           {"id": "f" * 16, "kind": "file",
                            "name": "n" * 200}]}]
    out = clean_messages(msgs)
    assert out[0]["artifacts"] == [
        {"id": "a" * 16, "kind": "pptx", "name": "B.pptx"},
        {"id": "f" * 16, "kind": "file", "name": "n" * 120},
    ]
    assert clean_messages(
        [{"role": "assistant", "content": "x", "artifacts": []}]
    )[0].get("artifacts") is None
    assert clean_messages(
        [{"role": "assistant", "content": "x", "artifacts": "nope"}]
    )[0].get("artifacts") is None


def test_artifact_isolation(art_env):
    FileStore("art-alice").register_output("A.pptx", b"PK\x03\x04x", "pptx")
    alice_id = FileStore("art-alice").list_outputs()[0].id
    assert FileStore("art-bob").list_outputs() == []
    assert FileStore("art-bob").get_output(alice_id) is None
    assert FileStore("art-bob").read_output(alice_id) is None
    assert FileStore("art-bob").read_output("../../x") is None
    UserStore("art-alice").save_chats(
        [], [{"role": "assistant", "content": "hi",
              "artifacts": [{"id": alice_id, "kind": "pptx",
                             "name": "A.pptx"}]}])
    bob, _ = UserStore("art-bob").load_chats()
    assert bob == {"chats": [], "current": []}


def test_failed_generation_registers_nothing(art_env):
    store = FileStore("art-user")
    with pytest.raises(StorageError):
        store.register_output("empty.pptx", b"", "pptx")
    assert store.list_outputs() == []


def test_retention_prunes_old_keeps_fresh(art_env):
    store = FileStore("art-user")
    old = store.register_output("old.docx", DOCX_BYTES, "docx")
    fresh = store.register_output("new.docx", DOCX_BYTES, "docx")
    reg_path = store.outputs_registry
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    reg[old.id]["created"] = time.time() - 31 * 86400
    reg_path.write_text(json.dumps(reg), encoding="utf-8")
    removed = store.prune_stale_outputs()
    assert removed == 1
    assert [m.id for m in store.list_outputs()] == [fresh.id]


def test_uploads_and_outputs_stay_separate(art_env):
    store = FileStore("art-user")
    store.save_upload(b"%PDF-1.4\n%\n", "in.pdf")
    store.register_output("out.docx", DOCX_BYTES, "docx")
    assert [(m.display_name, m.kind) for m in store.list_uploads()] == [
        ("in.pdf", "pdf")]
    assert [(m.display_name, m.kind) for m in store.list_outputs()] == [
        ("out.docx", "docx")]


def test_helper_labels():
    assert _artifact_kind_label("pptx", "x.pptx") == "PowerPoint"
    assert _artifact_kind_label("docx", "x.docx") == "Word document"
    assert _artifact_kind_label("file", "a.xyz") == "XYZ"
    assert _artifact_kind_label("file", "noext") == "File"
    assert _format_bytes(500) == "500 B"
    assert _format_bytes(2048) == "2 KB"
    assert _format_bytes("nope") == ""
    assert _rel_date(time.time()) == "Today"
    assert _rel_date("nope") == ""
    assert "Brief.pptx" in _artifact_card_html("Brief.pptx", "pptx", "sub")
    assert "Expired" in _artifact_card_html("x", "pptx", "Expired", expired=True)


# -- AppTest ------------------------------------------------------------

def test_case_a_generate_links_in_chat(art_env, monkeypatch):
    _use_user(monkeypatch, "art-gen")
    made = _stub_app_agent(monkeypatch, register=[("Brief.pptx", "pptx")])
    at = _run_app()
    at.text_input(key="composer_input_0").set_value("make slides").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assert len(made) == 1
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["artifacts"] == [{"id": made[0].id, "kind": "pptx",
                                  "name": "Brief.pptx"}]
    body = _md(at)
    assert 'class="poka-art"' in body
    assert "Brief.pptx" in body and "PowerPoint" in body
    assert any(k.startswith(f"dl-{made[0].id}") for k in _dl_keys(at))


def test_case_b_gallery_lists_artifact(art_env, monkeypatch):
    _use_user(monkeypatch, "art-gen")
    _stub_app_agent(monkeypatch, register=[("Brief.pptx", "pptx")])
    at = _run_app()
    at.text_input(key="composer_input_0").set_value("make slides").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    at.run(timeout=60)
    body = _md(at)
    assert "Artifacts" in body
    assert any(k.startswith("side-dl-") for k in _dl_keys(at))


def test_case_c_legacy_renders_without_linkage(art_env, monkeypatch):
    _use_user(monkeypatch, "art-legacy")
    FileStore("art-legacy").register_output("Old.docx", DOCX_BYTES, "docx")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "old answer"},
    ]
    at.run(timeout=120)
    assert not at.exception
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    body = _md(at)
    assert "Old.docx" in body  # gallery shows registry metadata
    assert 'class="poka-art-expired"' not in body


def test_case_d_multiple_artifacts(art_env, monkeypatch):
    _use_user(monkeypatch, "art-multi")
    made = _stub_app_agent(monkeypatch, register=[("A.pptx", "pptx"),
                                                  ("B.docx", "docx")])
    at = _run_app()
    at.text_input(key="composer_input_0").set_value("make both").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert len(meta["artifacts"]) == 2
    keys = _dl_keys(at)
    assert any(k.startswith(f"dl-{made[0].id}") for k in keys)
    assert any(k.startswith(f"dl-{made[1].id}") for k in keys)
    body = _md(at)
    assert "A.pptx" in body and "B.docx" in body


def test_case_e_gallery_isolated(art_env, monkeypatch):
    FileStore("art-alice").register_output("Alice.pptx", b"PK\x03\x04x", "pptx")
    _use_user(monkeypatch, "art-bob")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    body = _md(at)
    assert "Alice.pptx" not in body
    assert "No generated files yet." in body


def test_pruned_artifact_renders_expired(art_env, monkeypatch):
    _use_user(monkeypatch, "art-gone")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "old",
         "artifacts": [{"id": "0" * 16, "kind": "pptx", "name": "Gone.pptx"}]},
    ]
    at.run(timeout=120)
    assert not at.exception
    body = _md(at)
    assert "Gone.pptx" in body and "Expired" in body
    assert not any(k.startswith("dl-" + "0" * 16) for k in _dl_keys(at))


def test_files_section_lists_uploads(art_env, monkeypatch):
    _use_user(monkeypatch, "art-files")
    FileStore("art-files").save_upload(b"a,b\n1,2\n", "data.csv")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    body = _md(at)
    assert "data.csv" in body
    assert "No uploaded files yet" not in body


def test_metadata_intact_alongside_artifacts(art_env, monkeypatch):
    _use_user(monkeypatch, "art-meta")
    made =     _stub_app_agent(monkeypatch, register=[("B.pptx", "pptx")],
                           active_tier="Gemini 3.6 Flash", task_type="research",
                           tools_used=["create_pptx"])
    at = _run_app()
    at.session_state.deep_mode = True
    at.session_state.force_search = True
    at.run(timeout=60)
    at.text_input(key="composer_input_0").set_value("deck please").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    meta = [m for m in at.session_state.messages if m["role"] == "assistant"][0]
    assert meta["model"] == "Gemini 3.6 Flash"
    assert meta["mode"] == "deep"
    assert meta["searched"] is True
    assert meta["tools"] == ["create_pptx"]
    assert len(meta["artifacts"]) == 1 and meta["artifacts"][0]["id"] == made[0].id


def test_failed_send_creates_no_linkage(art_env, monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )

    def boom(user_input, chat_history=None, **kwargs):
        raise RuntimeError("generation exploded")

    monkeypatch.setattr(agent, "answer_with_fallback", boom)
    _use_user(monkeypatch, "art-fail")
    at = _run_app()
    at.text_input(key="composer_input_0").set_value("make it").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assert len(at.session_state.messages) == 1
    assert "artifacts" not in at.session_state.messages[0]
    assert FileStore("art-fail").list_outputs() == []
