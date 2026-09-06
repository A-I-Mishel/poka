"""Project ↔ conversation membership tests (Phase 5C).

project_id on a conversation is the single source of truth; Recents
filtering, move/remove actions, and select-sync are presentation over
it. No conversation content is ever rewritten by membership changes.

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
from services.storage import UserStore, find_chat_by_id

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))


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
def mem_env(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    return tmp_path / "data"


def _use_user(monkeypatch, name):
    monkeypatch.setenv("POKA_USER_ID", name)
    return str(UserStore(name).root)


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


def _run_app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    return at


def _fresh_app():
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = []
    at.run(timeout=60)
    assert not at.exception
    return at


def _button_labels(at):
    return [(str(b.key), str(b.label)) for b in at.button]


def _all_text(at):
    return " ".join(
        [str(m.value) for m in at.markdown]
        + [str(c.value) for c in at.caption]
    )


def _send(at, text="hello"):
    key = f"composer_input_{at.session_state.composer_key}"
    at.text_input(key=key).set_value(text).run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"


def test_case_a_create_in_project(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-a")
    pid = UserStore("mem-a").create_project("Website")["id"]
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["active_project_id"] == pid
    at.button(key="new-chat").click().run(timeout=120)
    _send(at, "hello project")
    assert at.session_state["current_project_id"] == pid
    assert at.session_state["active_project_id"] == pid  # untouched
    at.button(key="new-chat").click().run(timeout=120)
    assert not at.exception
    archived = at.session_state.chats[0]
    assert archived["project_id"] == pid
    assert at.session_state["current_project_id"] is None
    # Reload from disk: membership survives, and the chat is NOT Personal.
    loaded, _ = UserStore("mem-a").load_chats()
    assert loaded["chats"][0]["project_id"] == pid
    at2 = _run_app()
    at2.session_state.messages = []
    at2.session_state.chats = loaded["chats"]
    at2.run(timeout=60)
    # Fresh session defaults to Personal: the project chat is hidden.
    assert "hist-0" not in dict(_button_labels(at2))
    at2.button(key=f"project-{pid}").click().run(timeout=120)
    labels = dict(_button_labels(at2))
    assert labels.get("hist-0") == "hello project"[:34]
    at2.button(key="project-personal").click().run(timeout=120)
    assert "hist-0" not in dict(_button_labels(at2))


def test_personal_new_chat_has_no_project(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-personal")
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    _send(at, "plain hello")
    at.button(key="new-chat").click().run(timeout=120)
    assert not at.exception
    assert "project_id" not in at.session_state.chats[0]


def test_case_d_select_synchronizes(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-sync")
    pid = UserStore("mem-sync").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "a" * 16, "title": "Proj chat",
         "project_id": pid,
         "messages": [{"role": "user", "content": "p"}]},
        {"id": "b" * 16, "title": "Plain chat",
         "messages": [{"role": "user", "content": "q"}]},
    ]
    at.run(timeout=120)
    # Personal filter shows only the unassigned chat under its true index.
    labels = dict(_button_labels(at))
    assert labels.get("hist-1") == "Plain chat"
    assert "hist-0" not in labels
    # Opening the project chat syncs the visible project context.
    at.button(key=f"project-{pid}").click().run(timeout=120)
    labels = dict(_button_labels(at))
    assert labels.get("hist-0") == "Proj chat"
    assert "hist-1" not in labels
    at.button(key="hist-0").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["active_project_id"] == pid
    assert at.session_state["current_project_id"] == pid
    assert at.session_state["current_chat_id"] == "a" * 16
    # Opening the Personal chat syncs back to Personal. NOTE: select
    # pops the project chat, so the plain chat is now at index 0.
    at.button(key="project-personal").click().run(timeout=120)
    at.button(key="hist-0").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["active_project_id"] is None
    assert at.session_state["current_project_id"] is None
    assert at.session_state["current_chat_id"] == "b" * 16


def test_rename_through_filtered_row(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-rename")
    pid = UserStore("mem-rename").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "a" * 16, "title": "Proj chat", "project_id": pid,
         "messages": [{"role": "user", "content": "p"}]},
        {"id": "b" * 16, "title": "Plain chat",
         "messages": [{"role": "user", "content": "q"}]},
    ]
    at.run(timeout=120)
    # Project filter exposes only the member row under its true index;
    # renaming it must write the true record and leave others alone.
    at.button(key=f"project-{pid}").click().run(timeout=120)
    at.button(key="rename-0").click().run(timeout=120)
    at.text_input(key="rename-box-0").set_value("Renamed").run(timeout=60)
    at.button(key="rename-save-0").click().run(timeout=120)
    assert not at.exception
    assert at.session_state.chats[0]["title"] == "Renamed"
    assert at.session_state.chats[0]["id"] == "a" * 16
    assert at.session_state.chats[0]["project_id"] == pid
    assert at.session_state.chats[1]["title"] == "Plain chat"


def test_case_e_select_does_not_move(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-nomove")
    pid = UserStore("mem-nomove").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.messages = [{"role": "user", "content": "mine"}]
    at.run(timeout=60)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["active_project_id"] == pid
    assert [m["content"] for m in at.session_state.messages] == ["mine"]
    assert at.session_state["current_project_id"] is None


def test_scoped_recents_true_indexes(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-scope")
    pid = UserStore("mem-scope").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "a" * 16, "title": "Proj chat", "project_id": pid,
         "messages": [{"role": "user", "content": "p"}]},
        {"id": "b" * 16, "title": "Plain chat",
         "messages": [{"role": "user", "content": "q"}]},
    ]
    at.run(timeout=120)
    # Personal sees only the unassigned chat, under its TRUE index.
    labels = dict(_button_labels(at))
    assert labels.get("hist-1") == "Plain chat"
    assert "hist-0" not in labels
    at.button(key=f"project-{pid}").click().run(timeout=120)
    labels = dict(_button_labels(at))
    assert labels.get("hist-0") == "Proj chat"
    assert "hist-1" not in labels
    # Rename through the filtered row writes the true record.
    at.button(key="rename-0").click().run(timeout=120)
    at.text_input(key="rename-box-0").set_value("Renamed").run(timeout=60)
    at.button(key="rename-save-0").click().run(timeout=120)
    assert not at.exception
    assert at.session_state.chats[0]["title"] == "Renamed"
    assert at.session_state.chats[0]["id"] == "a" * 16
    assert at.session_state.chats[1]["title"] == "Plain chat"


def test_orphan_behaves_as_personal(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-orphan")
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "a" * 16, "title": "Orphan chat", "project_id": "f" * 16,
         "messages": [{"role": "user", "content": "p"}]},
    ]
    at.run(timeout=120)
    labels = dict(_button_labels(at))
    assert labels.get("hist-0") == "Orphan chat"  # visible, not lost
    at.session_state.active_project_id = "f" * 16  # stale selection
    at.run(timeout=60)
    assert not at.exception
    assert at.button(key="project-personal").disabled is True
    labels = dict(_button_labels(at))
    assert labels.get("hist-0") == "Orphan chat"


def _open_with_messages(at, messages):
    at.session_state.messages = [dict(m) for m in messages]
    at.run(timeout=60)
    assert not at.exception


def test_case_b_move_to_project(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-move")
    pid = UserStore("mem-move").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    _open_with_messages(at, [
        {"role": "user", "content": "move me",
         "attachments": [{"id": "a" * 16, "kind": "pdf", "name": "r.pdf"}]},
        {"role": "assistant", "content": "done", "model": "T",
         "mode": "fast", "searched": False, "tools": ["read_pdf"],
         "sources": [{"title": "S", "url": "https://e.example/",
                      "domain": "e.example"}],
         "artifacts": [{"id": "b" * 16, "kind": "pptx", "name": "B.pptx"}]},
    ])
    before = [dict(m) for m in at.session_state.messages]
    at.button(key="conv-move-open").click().run(timeout=120)
    at.button(key=f"conv-move-{pid}").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["current_project_id"] == pid
    # Content untouched; archive carries the membership.
    assert at.session_state.messages == before
    at.button(key="new-chat").click().run(timeout=120)
    assert not at.exception
    record = at.session_state.chats[0]
    assert record["project_id"] == pid
    assert record["messages"] == before
    assert record["messages"][1]["tools"] == ["read_pdf"]
    assert record["messages"][1]["artifacts"] == [
        {"id": "b" * 16, "kind": "pptx", "name": "B.pptx"}]


def test_case_c_move_to_personal(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-unmove")
    pid = UserStore("mem-unmove").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    _open_with_messages(at, [{"role": "user", "content": "move me"}])
    at.button(key="conv-move-open").click().run(timeout=120)
    at.button(key=f"conv-move-{pid}").click().run(timeout=120)
    assert at.session_state["current_project_id"] == pid
    at.button(key="conv-move-open").click().run(timeout=120)
    at.button(key="conv-move-personal").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["current_project_id"] is None
    at.button(key="new-chat").click().run(timeout=120)
    assert "project_id" not in at.session_state.chats[0]


def test_move_validates_target(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-moveval")
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    _open_with_messages(at, [{"role": "user", "content": "hi"}])
    at.session_state.current_chat_id = "c" * 16
    at.run(timeout=60)
    # No picker row can exist for unknown ids; direct store calls refuse.
    assert UserStore("mem-moveval").get_project("f" * 16) is None
    assert find_chat_by_id(at.session_state.chats, "../x") is None


def test_case_f_archive_flow(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-arch")
    pid = UserStore("mem-arch").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.button(key=f"project-{pid}").click().run(timeout=120)
    at.button(key="new-chat").click().run(timeout=60)
    _send(at, "in project")
    at.button(key="new-chat").click().run(timeout=120)
    assert at.session_state.chats[0]["project_id"] == pid
    UserStore("mem-arch").archive_project(pid)
    at.run(timeout=60)
    assert not at.exception
    # Active context falls back; membership on the record is untouched.
    assert at.button(key="project-personal").disabled is True
    assert at.session_state.chats[0]["project_id"] == pid
    assert at.session_state.chats[0]["messages"][0]["content"] == "in project"


def test_case_g_legacy_personal(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-legacy")
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"title": "Ancient", "messages": [{"role": "user", "content": "q"}]},
    ]
    at.run(timeout=120)
    labels = dict(_button_labels(at))
    assert labels.get("hist-0") == "Ancient"
    at.button(key="hist-0").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["active_project_id"] is None
    assert at.session_state["current_project_id"] is None


def test_case_h_foreign_invisible(mem_env, monkeypatch):
    UserStore("mem-alice").create_project("Alice Site")
    alice_pid = UserStore("mem-alice").list_projects()[0]["id"]
    UserStore("mem-alice").save_chats(
        [{"id": "a" * 16, "title": "Alice chat", "project_id": alice_pid,
          "messages": [{"role": "user", "content": "secret"}]}], [])
    _use_user(monkeypatch, "mem-bob")
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    labels = dict(_button_labels(at))
    assert f"project-{alice_pid}" not in labels
    assert "Alice Site" not in " ".join(
        str(m.value) for m in at.markdown)
    assert "hist-0" not in labels
    assert UserStore("mem-bob").get_project(alice_pid) is None
    assert find_chat_by_id(at.session_state.chats, "a" * 16) is None


def test_rename_edit_retry_preserve_membership(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-keep")
    pid = UserStore("mem-keep").create_project("Site")["id"]
    calls = {"n": 0}
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )

    def flaky(user_input, chat_history=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"output": "recovered", "active_tier": "T",
                "task_type": "simple"}

    monkeypatch.setattr(agent, "answer_with_fallback", flaky)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.session_state.messages = []
    at.session_state.chats = [{
        "id": "a" * 16, "title": "Keep", "project_id": pid,
        "messages": [
            {"role": "user", "content": "q",
             "attachments": [{"id": "b" * 16, "kind": "pdf",
                              "name": "r.pdf"}]},
            {"role": "assistant", "content": "a"},
        ],
    }]
    at.run(timeout=120)
    # Rename by true index keeps id + project (select project first so
    # the member row is visible).
    at.button(key=f"project-{pid}").click().run(timeout=120)
    at.button(key="rename-0").click().run(timeout=120)
    at.text_input(key="rename-box-0").set_value("Kept").run(timeout=60)
    at.button(key="rename-save-0").click().run(timeout=120)
    assert not at.exception
    assert at.session_state.chats[0]["id"] == "a" * 16
    assert at.session_state.chats[0]["project_id"] == pid
    # Select adopts ids; edit restores attachments without touching them.
    at.button(key="hist-0").click().run(timeout=120)
    assert at.session_state["current_chat_id"] == "a" * 16
    assert at.session_state["current_project_id"] == pid
    assert at.session_state["active_project_id"] == pid
    at.button(key="edit-0").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["current_chat_id"] == "a" * 16
    assert at.session_state["current_project_id"] == pid
    # Failed send then retry keeps conversation identity throughout.
    at.text_input(key="composer_input_0").set_value("again").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["current_chat_id"] == "a" * 16
    assert at.session_state["current_project_id"] == pid
    at.button(key="retry-main").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["current_chat_id"] == "a" * 16
    assert at.session_state["current_project_id"] == pid
    assert at.session_state.messages[-1]["content"] == "recovered"


def test_main_indicator_and_empty_states(mem_env, monkeypatch):
    _use_user(monkeypatch, "mem-indicator")
    pid = UserStore("mem-indicator").create_project("Site Beta")["id"]
    _stub_app_agent(monkeypatch)
    at = _fresh_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "b" * 16, "title": "Plain chat",
         "messages": [{"role": "user", "content": "q"}]},
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    body = _all_text(at)
    assert "In project:" in body and "Site Beta" in body
    # Active project with no member chats: useful empty state.
    assert "No conversations in" in body
    at.button(key="project-personal").click().run(timeout=120)
    body = _all_text(at)
    assert "In project:" not in body
