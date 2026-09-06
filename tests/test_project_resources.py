"""Project-scoped resource derivation tests (Phase 5D).

Membership (project_id on conversations) is the only direct project
relationship. Files, artifacts, and sources are derived views over
member conversations: no copies, no re-owning, no new registries.

Hermetic: tmp POKA_DATA_DIR + env identity. Agent stubbed.
"""

import os
import sys

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
from ui.project_resources import (
    MAX_PROJECT_SOURCES,
    artifact_entries_in,
    member_conversations,
    messages_of,
    open_bucket,
    project_bucket,
    source_entries_in,
    upload_ids_in,
)

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))

PDF_BYTES = b"%PDF-1.4\n%\n"
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
def res_env(tmp_path, monkeypatch):
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


def _section(body, label, end_labels=("Artifacts", "Sources", "Stats", "Memory", "Files", "Mode", "Recents", "Projects", "Workspace")):
    """Slice one sidebar section's markdown (labels are stable)."""
    start = body.find(f'<p class="section-label">{label}</p>')
    if start < 0:
        return ""
    rest = body[start:]
    cuts = [rest.find(f'<p class="section-label">{other}</p>', len(label) + 30)
            for other in end_labels if other != label]
    cuts = [c for c in cuts if c > 0]
    return rest[:min(cuts)] if cuts else rest


def _stub_app_agent(monkeypatch, **extra):
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )
    payload = {"output": "ok", "active_tier": "T", "task_type": "simple"}
    payload.update(extra)

    def fake_answer(user_input, chat_history=None, **kwargs):
        return dict(payload)

    monkeypatch.setattr(agent, "answer_with_fallback", fake_answer)


def _convo(cid, pid, messages):
    record = {"id": cid, "title": "T" + cid[:4], "messages": messages}
    if pid is not None:
        record["project_id"] = pid
    return record


def _user_msg(*att_ids, kinds=None):
    kinds = kinds or (["pdf"] * len(att_ids))
    return {"role": "user", "content": "q",
            "attachments": [{"id": uid, "kind": kind, "name": f"{uid[:4]}.dat"}
                            for uid, kind in zip(att_ids, kinds)]}


# -- pure derivation --------------------------------------------------------

def test_files_derived_from_members():
    pid, other = "a" * 16, "b" * 16
    chats = [
        _convo("c" * 16, pid, [_user_msg("u" * 16)]),
        _convo("d" * 16, other, [_user_msg("v" * 16)]),
        _convo("e" * 16, None, [_user_msg("w" * 16)]),
    ]
    members = member_conversations(chats, pid, {pid, other})
    assert upload_ids_in(messages_of(members)) == ["u" * 16]


def test_shared_file_deduped_across_projects():
    shared, only_a, only_b = "s" * 16, "x" * 16, "y" * 16
    pid_a, pid_b = "a" * 16, "b" * 16
    chats = [
        _convo("c" * 16, pid_a, [_user_msg(shared), _user_msg(only_a)]),
        _convo("d" * 16, pid_b, [_user_msg(shared), _user_msg(only_b)]),
    ]
    ids_a = upload_ids_in(messages_of(member_conversations(chats, pid_a, {pid_a, pid_b})))
    ids_b = upload_ids_in(messages_of(member_conversations(chats, pid_b, {pid_a, pid_b})))
    assert ids_a == [shared, only_a]
    assert ids_b == [shared, only_b]


def test_multi_attachment_contributes_all():
    msgs = [_user_msg("a" * 16, "b" * 16, "c" * 16,
                      kinds=["pdf", "csv", "image"])]
    assert upload_ids_in(msgs) == ["a" * 16, "b" * 16, "c" * 16]


def test_artifact_entries_validated():
    msgs = [{"role": "assistant", "content": "x", "artifacts": [
        {"id": "a" * 16, "kind": "pptx", "name": "A.pptx"},
        {"id": "", "kind": "pptx", "name": "empty"},
        {"id": "b" * 16, "kind": "pdf", "name": "wrong-kind"},
        {"id": "c" * 16, "kind": "docx", "name": ""},
        "junk",
    ]}]
    assert artifact_entries_in(msgs) == [
        {"id": "a" * 16, "kind": "pptx", "name": "A.pptx"}]


def test_sources_deduped_validated():
    good = {"title": "T", "url": "https://e.example/a", "domain": "e.example"}
    msgs = [{"role": "assistant", "content": "x", "sources": [
        good,
        {"title": "T2", "url": "HTTPS://E.EXAMPLE/A", "domain": "e.example"},
        {"title": "U", "url": "https://u.example/", "domain": "u.example"},
        {"title": "Bad", "url": "javascript:evil()"},
        {"nope": True},
    ]}]
    assert source_entries_in(msgs) == [
        good,
        {"title": "U", "url": "https://u.example/", "domain": "u.example"},
    ]


def test_member_edge_cases():
    assert member_conversations("junk", "a" * 16, {"a" * 16}) == []
    assert member_conversations(None, None, set()) == []
    assert upload_ids_in("junk") == []
    assert artifact_entries_in(None) == []
    assert source_entries_in([{"role": "assistant"}]) == []
    assert messages_of([{"no": "messages"}, "junk"]) == []
    assert project_bucket({"project_id": "a" * 16}, {"a" * 16}) == "a" * 16
    assert project_bucket({"project_id": "f" * 16}, {"a" * 16}) is None
    assert project_bucket({"project_id": "archived"}, set()) is None
    assert project_bucket({}, set()) is None
    assert project_bucket("junk", set()) is None
    assert open_bucket("a" * 16, {"a" * 16}) == "a" * 16
    assert open_bucket("f" * 16, {"a" * 16}) is None
    assert open_bucket(None, set()) is None


# -- AppTest: views -----------------------------------------------------------

def test_case_a_shared_pdf_once(res_env, monkeypatch):
    _use_user(monkeypatch, "res-a")
    pid = UserStore("res-a").create_project("Site")["id"]
    seeded = FileStore("res-a").save_upload(PDF_BYTES, "shared.pdf")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        _convo("c" * 16, pid, [_user_msg(seeded.id)]),
        _convo("d" * 16, pid, [_user_msg(seeded.id)]),
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    files = _section(_md(at), "Files")
    assert files.count(">shared.pdf<") == 1


def test_personal_files_unchanged(res_env, monkeypatch):
    _use_user(monkeypatch, "res-personal-files")
    seeded = FileStore("res-personal-files").save_upload(PDF_BYTES, "loose.pdf")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    body = _md(at)
    assert "loose.pdf" in body
    assert seeded.id is not None


def test_case_b_project_artifacts(res_env, monkeypatch):
    _use_user(monkeypatch, "res-b")
    pid = UserStore("res-b").create_project("Site")["id"]
    meta = FileStore("res-b").register_output("Brief.docx", DOCX_BYTES, "docx")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "c" * 16, "title": "T", "project_id": pid,
         "messages": [{"role": "assistant", "content": "done",
                       "artifacts": [{"id": meta.id, "kind": "docx",
                                      "name": "Brief.docx"}]}]},
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    body = _md(at)
    assert "Brief.docx" in body
    assert any(k == f"side-dl-{meta.id}" for k, _ in
               [(str(b.key), str(b.label)) for b in at.download_button])


def test_legacy_unlinked_excluded_from_project(res_env, monkeypatch):
    _use_user(monkeypatch, "res-legacy")
    pid = UserStore("res-legacy").create_project("Site")["id"]
    FileStore("res-legacy").register_output("Old.docx", DOCX_BYTES, "docx")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    body = _md(at)
    assert "Old.docx" not in body  # no message links it: excluded
    at.button(key="project-personal").click().run(timeout=120)
    assert "Old.docx" in _md(at)  # Personal registry view keeps it


def test_case_c_project_sources(res_env, monkeypatch):
    _use_user(monkeypatch, "res-c")
    pid = UserStore("res-c").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "c" * 16, "title": "T", "project_id": pid,
         "messages": [{"role": "assistant", "content": "answer",
                       "sources": [
                           {"title": "Mars News",
                            "url": "https://example.com/mars",
                            "domain": "example.com"},
                           {"title": "Bad", "url": "javascript:evil()"},
                       ]}]},
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-sources").click().run(timeout=120)
    body = _md(at)
    assert "Mars News" in body and "example.com" in body
    assert "https://example.com/mars" in body
    assert "javascript" not in body


def test_case_d_move_updates_views(res_env, monkeypatch):
    _use_user(monkeypatch, "res-d")
    pid = UserStore("res-d").create_project("Site")["id"]
    seeded = FileStore("res-d").save_upload(PDF_BYTES, "move.pdf")
    meta = FileStore("res-d").register_output("Move.docx", DOCX_BYTES, "docx")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "c" * 16, "title": "T", "project_id": pid,
         "messages": [
             {"role": "user", "content": "q",
              "attachments": [{"id": seeded.id, "kind": "pdf",
                               "name": "move.pdf"}]},
             {"role": "assistant", "content": "a",
              "artifacts": [{"id": meta.id, "kind": "docx",
                             "name": "Move.docx"}],
              "sources": [{"title": "S", "url": "https://s.example/",
                           "domain": "s.example"}]},
         ]},
    ]
    at.run(timeout=60)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    body = _md(at)
    assert "move.pdf" in _section(body, "Files")
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    body = _md(at)
    assert "Move.docx" in _section(body, "Artifacts")
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-sources").click().run(timeout=120)
    body = _md(at)
    assert "s.example" in _section(body, "Sources")
    # Open conversation (Personal) with a fresh file is not yet included.
    at.session_state.messages = [
        {"role": "user", "content": "new",
         "attachments": [{"id": seeded.id, "kind": "pdf",
                          "name": "move.pdf"}]},
    ]
    at.run(timeout=60)
    at.button(key="conv-move-open").click().run(timeout=120)
    at.button(key=f"conv-move-{pid}").click().run(timeout=120)
    assert not at.exception
    # Project still active (its row is disabled); the open file joins.
    assert at.button(key=f"project-{pid}").disabled is True
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    assert _section(_md(at), "Files").count(">move.pdf<") == 1  # still once


def test_case_e_move_out_hides_views(res_env, monkeypatch):
    _use_user(monkeypatch, "res-e")
    pid = UserStore("res-e").create_project("Site")["id"]
    seeded = FileStore("res-e").save_upload(PDF_BYTES, "leave.pdf")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = [
        {"role": "user", "content": "q",
         "attachments": [{"id": seeded.id, "kind": "pdf",
                          "name": "leave.pdf"}]},
    ]
    at.session_state.current_project_id = pid
    at.run(timeout=60)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    assert "leave.pdf" in _section(_md(at), "Files")
    at.button(key="back-to-chat").click().run(timeout=120)
    at.button(key="conv-move-open").click().run(timeout=120)
    at.button(key="conv-move-personal").click().run(timeout=120)
    assert not at.exception
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    files = _section(_md(at), "Files")
    assert "leave.pdf" not in files
    assert "No files in this project yet." in files


def test_case_f_forged_ids_skipped(res_env, monkeypatch):
    _use_user(monkeypatch, "res-f")
    pid = UserStore("res-f").create_project("Site")["id"]
    FileStore("res-alice").save_upload(PDF_BYTES, "alice.pdf")
    alice_id = FileStore("res-alice").list_uploads()[0].id
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "c" * 16, "title": "T", "project_id": pid,
         "messages": [{"role": "user", "content": "q",
                       "attachments": [{"id": alice_id, "kind": "pdf",
                                        "name": "alice.pdf"},
                                       {"id": "not-an-id", "kind": "pdf",
                                        "name": "x.pdf"}]}]},
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    body = _md(at)
    assert "alice.pdf" not in body
    assert "No files in this project yet." in body


def test_case_g_expired_artifact(res_env, monkeypatch):
    _use_user(monkeypatch, "res-g")
    pid = UserStore("res-g").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "c" * 16, "title": "T", "project_id": pid,
         "messages": [{"role": "assistant", "content": "old",
                       "artifacts": [{"id": "0" * 16, "kind": "pptx",
                                      "name": "Gone.pptx"}]}]},
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    body = _md(at)
    assert "Gone.pptx" in body and "Expired" in body
    assert not any(str(b.key).startswith("side-dl-" + "0" * 16)
                   for b in at.download_button)


def test_case_h_project_empty_states(res_env, monkeypatch):
    _use_user(monkeypatch, "res-h")
    pid = UserStore("res-h").create_project("Empty")["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "b" * 16, "title": "Plain chat",
         "messages": [{"role": "user", "content": "q"}]},
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    body = _md(at)
    assert "No conversations in" in body
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    assert "No files in this project yet." in _md(at)
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    assert "No generated files in this project yet." in _md(at)
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-sources").click().run(timeout=120)
    assert "No web sources in this project yet." in _md(at)


def test_archived_members_visible_as_personal(res_env, monkeypatch):
    _use_user(monkeypatch, "res-arch")
    pid = UserStore("res-arch").create_project("Site")["id"]
    seeded = FileStore("res-arch").save_upload(PDF_BYTES, "a.pdf")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "c" * 16, "title": "T", "project_id": pid,
         "messages": [{"role": "user", "content": "q",
                       "attachments": [{"id": seeded.id, "kind": "pdf",
                                        "name": "a.pdf"}]}]},
    ]
    at.run(timeout=120)
    UserStore("res-arch").archive_project(pid)
    at.run(timeout=60)
    assert not at.exception
    body = _md(at)
    assert at.button(key="project-personal").disabled is True
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    assert "a.pdf" in _md(at)  # member falls back to Personal views


def test_cross_user_resources_invisible(res_env, monkeypatch):
    FileStore("res-alice").save_upload(PDF_BYTES, "alice.pdf")
    FileStore("res-alice").register_output("Alice.docx", DOCX_BYTES, "docx")
    _use_user(monkeypatch, "res-bob")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    body = _md(at)
    assert "alice.pdf" not in body
    assert "Alice.docx" not in body
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    assert "No uploaded files yet" in _md(at)
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    assert "No generated files yet." in _md(at)


def test_personal_sources_derived(res_env, monkeypatch):
    _use_user(monkeypatch, "res-psrc")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "c" * 16, "title": "T",
         "messages": [{"role": "assistant", "content": "a",
                       "sources": [{"title": "P",
                                    "url": "https://p.example/",
                                    "domain": "p.example"}]}]},
    ]
    at.run(timeout=120)
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-sources").click().run(timeout=120)
    assert "p.example" in _md(at)


def test_downloads_metadata_vault_intact(res_env, monkeypatch):
    _use_user(monkeypatch, "res-intact")
    pid = UserStore("res-intact").create_project("Site")["id"]
    meta = FileStore("res-intact").register_output("K.docx", DOCX_BYTES, "docx")
    _stub_app_agent(monkeypatch, active_tier="T", tools_used=["create_docx"])
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "c" * 16, "title": "T", "project_id": pid,
         "messages": [{"role": "assistant", "content": "done", "model": "T",
                       "artifacts": [{"id": meta.id, "kind": "docx",
                                      "name": "K.docx"}]}]},
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    assert any(str(b.key) == f"side-dl-{meta.id}" for b in at.download_button)
    from services import memory as mem_mod
    assert mem_mod.list_memory_facts() == []
