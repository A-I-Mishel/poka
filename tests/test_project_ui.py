"""Projects sidebar UI tests (Phase 5B).

The Projects block is presentation over the Phase 5A data foundation:
list/Personal/create/rename/archive/select with per-render registry
resolution. No conversation filtering or membership changes here.

Hermetic: tmp POKA_DATA_DIR + env identity. Agent stubbed where the
app runs; no live providers.
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
from services.storage import UserStore

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
def ui_env(tmp_path, monkeypatch):
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
    at.session_state.messages = []
    at.session_state.chats = []
    at.run(timeout=60)
    assert not at.exception
    return at


def _md(at):
    return " ".join(str(m.value) for m in at.markdown)


def _button_labels(at):
    return [(str(b.key), str(b.label)) for b in at.button]


def test_case_a_personal_visible_by_default(ui_env, monkeypatch):
    _use_user(monkeypatch, "ui-personal")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    labels = dict(_button_labels(at))
    assert labels.get("project-personal") == "Personal"
    assert labels.get("project-create") == "+"
    # Personal is the active (disabled) row when nothing is selected.
    assert at.button(key="project-personal").disabled is True
    assert "Projects" in _md(at)


def test_case_b_create_project(ui_env, monkeypatch):
    _use_user(monkeypatch, "ui-create")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key="project-create").click().run(timeout=120)
    assert not at.exception
    at.text_input(key="project-name-box").set_value("Website").run(timeout=60)
    at.button(key="project-create-save").click().run(timeout=120)
    assert not at.exception
    labels = dict(_button_labels(at))
    assert any(
        key.startswith("project-") and label == "Website"
        for key, label in labels.items()
    )
    # The new project becomes active; Personal is no longer disabled.
    assert at.button(key="project-personal").disabled is False
    stored = UserStore("ui-create").list_projects()
    assert len(stored) == 1 and stored[0]["name"] == "Website"
    assert at.session_state["active_project_id"] == stored[0]["id"]


def test_create_invalid_name(ui_env, monkeypatch):
    _use_user(monkeypatch, "ui-badname")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key="project-create").click().run(timeout=120)
    at.text_input(key="project-name-box").set_value("   ").run(timeout=60)
    at.button(key="project-create-save").click().run(timeout=120)
    assert not at.exception
    assert UserStore("ui-badname").list_projects() == []


def test_create_long_name_truncated(ui_env, monkeypatch):
    _use_user(monkeypatch, "ui-longname")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key="project-create").click().run(timeout=120)
    at.text_input(key="project-name-box").set_value("n" * 61).run(timeout=60)
    at.button(key="project-create-save").click().run(timeout=120)
    assert not at.exception
    stored = UserStore("ui-longname").list_projects()
    assert len(stored) == 1 and stored[0]["name"] == "n" * 60


def test_case_c_select_project(ui_env, monkeypatch):
    _use_user(monkeypatch, "ui-select")
    first = UserStore("ui-select").create_project("Alpha")["id"]
    second = UserStore("ui-select").create_project("Beta")["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key=f"project-{second}").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["active_project_id"] == second
    assert at.button(key=f"project-{second}").disabled is True
    assert at.button(key=f"project-{first}").disabled is False
    assert at.button(key="project-personal").disabled is False
    at.button(key="project-personal").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["active_project_id"] is None
    assert at.button(key="project-personal").disabled is True


def test_case_d_rename_project(ui_env, monkeypatch):
    _use_user(monkeypatch, "ui-rename")
    pid = UserStore("ui-rename").create_project("Old")["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key=f"project-pencil-{pid}").click().run(timeout=120)
    assert not at.exception
    at.text_input(key=f"project-rename-box-{pid}").set_value("New").run(timeout=60)
    at.button(key=f"project-rename-save-{pid}").click().run(timeout=120)
    assert not at.exception
    stored = UserStore("ui-rename").get_project(pid)
    assert stored is not None and stored["name"] == "New"
    assert stored["id"] == pid
    labels = dict(_button_labels(at))
    assert labels.get(f"project-{pid}") == "New"


def test_case_e_archive_project(ui_env, monkeypatch):
    _use_user(monkeypatch, "ui-archive")
    pid = UserStore("ui-archive").create_project("Gone")["id"]
    seeded_chats = [{"id": "a" * 16, "title": "Keep me",
                     "messages": [{"role": "user", "content": "hi"}]}]
    UserStore("ui-archive").save_chats(seeded_chats, [])
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key=f"project-pencil-{pid}").click().run(timeout=120)
    at.button(key=f"project-archive-{pid}").click().run(timeout=120)
    assert not at.exception
    at.button(key="project-archive-confirm").click().run(timeout=120)
    assert not at.exception
    labels = dict(_button_labels(at))
    assert f"project-{pid}" not in labels
    assert labels.get("project-personal") == "Personal"
    # Data retained: record archived, conversations untouched.
    stored = UserStore("ui-archive").get_project(pid)
    assert stored is not None and stored["archived"] is True
    assert stored["name"] == "Gone"
    loaded, _ = UserStore("ui-archive").load_chats()
    assert loaded["chats"][0]["title"] == "Keep me"


def test_case_f_stale_selection_falls_back(ui_env, monkeypatch):
    _use_user(monkeypatch, "ui-stale")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.active_project_id = "f" * 16  # never existed
    at.run(timeout=60)
    assert not at.exception
    assert at.button(key="project-personal").disabled is True
    pid = UserStore("ui-stale").create_project("Temp")["id"]
    at.session_state.active_project_id = pid
    at.run(timeout=60)
    UserStore("ui-stale").archive_project(pid)  # changed under us
    at.run(timeout=60)
    assert not at.exception
    assert at.button(key="project-personal").disabled is True


def test_projects_isolated_between_users(ui_env, monkeypatch):
    UserStore("ui-alice").create_project("Alice Project")
    alice_id = UserStore("ui-alice").list_projects()[0]["id"]
    _use_user(monkeypatch, "ui-bob")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    labels = dict(_button_labels(at))
    assert f"project-{alice_id}" not in labels
    assert "Alice Project" not in _md(at)
    assert labels.get("project-personal") == "Personal"


def test_no_conversation_filtering_yet(ui_env, monkeypatch):
    # Phase 5B establishes selection context only: Recents, Files,
    # Artifacts, Memory, and metadata render exactly as before.
    _use_user(monkeypatch, "ui-nofilter")
    UserStore("ui-nofilter").create_project("P1")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi", "model": "T",
         "mode": "fast", "searched": False},
    ]
    at.session_state.chats = [{
        "id": "b" * 16, "title": "Old chat",
        "messages": [{"role": "user", "content": "old"}],
    }]
    at.run(timeout=120)
    assert not at.exception
    labels = dict(_button_labels(at))
    assert labels.get("hist-0") == "Old chat"  # recents unfiltered
    body = _md(at)
    assert "Poka" in body
    assert at.session_state.chats[0]["id"] == "b" * 16  # untouched


def test_archived_project_row_hidden_but_record_kept(ui_env, monkeypatch):
    _use_user(monkeypatch, "ui-hidden")
    pid = UserStore("ui-hidden").create_project("Hidden")["id"]
    UserStore("ui-hidden").archive_project(pid)
    _stub_app_agent(monkeypatch)
    at = _run_app()
    labels = dict(_button_labels(at))
    assert f"project-{pid}" not in labels
    assert at.button(key="project-personal").disabled is True
