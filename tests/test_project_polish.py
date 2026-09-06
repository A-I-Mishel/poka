"""Project workspace polish tests (Phase 5F).

Visual-behavioral contracts only: active states, switching, forms,
empty states, scoped visibility, and the CSS hooks they depend on.
No data-model, agent, or storage semantics change here.

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
def polish_env(tmp_path, monkeypatch):
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


def _labels(at):
    return {str(b.key): str(b.label) for b in at.button}


def _text(at):
    return " ".join(
        [str(m.value) for m in at.markdown]
        + [str(c.value) for c in at.caption]
    )


def test_active_state_personal_by_default(polish_env, monkeypatch):
    _use_user(monkeypatch, "pol-active")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    assert at.button(key="project-personal").disabled is True


def test_switching_updates_everything(polish_env, monkeypatch):
    _use_user(monkeypatch, "pol-switch")
    alpha = UserStore("pol-switch").create_project("Alpha")["id"]
    beta = UserStore("pol-switch").create_project("Beta")["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key=f"project-{alpha}").click().run(timeout=120)
    assert not at.exception
    assert at.button(key=f"project-{alpha}").disabled is True
    assert at.button(key=f"project-{beta}").disabled is False
    assert at.button(key="project-personal").disabled is False
    assert "Alpha" in _text(at)
    at.button(key=f"project-{beta}").click().run(timeout=120)
    assert not at.exception
    assert at.button(key=f"project-{beta}").disabled is True
    assert at.button(key=f"project-{alpha}").disabled is False
    assert "Beta" in _text(at)
    # Old project content does not linger: its editor is gone with it.
    at.button(key="project-personal").click().run(timeout=120)
    assert not at.exception
    assert at.button(key="project-personal").disabled is True
    assert at.button(key=f"project-{alpha}").disabled is False
    assert "In project:" not in _text(at)


def test_personal_fallback_stale(polish_env, monkeypatch):
    _use_user(monkeypatch, "pol-stale")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.active_project_id = "f" * 16
    at.run(timeout=60)
    assert not at.exception
    assert at.button(key="project-personal").disabled is True


def test_create_form_lifecycle(polish_env, monkeypatch):
    _use_user(monkeypatch, "pol-create")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key="project-create").click().run(timeout=120)
    assert not at.exception
    at.text_input(key="project-name-box")
    at.button(key="project-create-cancel").click().run(timeout=120)
    assert not at.exception
    assert UserStore("pol-create").list_projects() == []
    with pytest.raises(KeyError):
        at.button(key="project-name-box")
    at.button(key="project-create").click().run(timeout=120)
    at.text_input(key="project-name-box").set_value("  ").run(timeout=60)
    at.button(key="project-create-save").click().run(timeout=120)
    assert not at.exception
    assert UserStore("pol-create").list_projects() == []


def test_rename_archive_ui_flow(polish_env, monkeypatch):
    _use_user(monkeypatch, "pol-rename")
    pid = UserStore("pol-rename").create_project("Old")["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.button(key=f"project-pencil-{pid}").click().run(timeout=120)
    assert not at.exception
    assert at.text_input(key=f"project-rename-box-{pid}").value == "Old"
    at.text_input(key=f"project-rename-box-{pid}").set_value("New").run(timeout=60)
    at.button(key=f"project-rename-save-{pid}").click().run(timeout=120)
    assert UserStore("pol-rename").get_project(pid)["name"] == "New"
    at.button(key=f"project-pencil-{pid}").click().run(timeout=120)
    at.button(key=f"project-archive-{pid}").click().run(timeout=120)
    assert not at.exception
    assert "leave the list" in _text(at)
    at.button(key="project-archive-dismiss").click().run(timeout=120)
    assert UserStore("pol-rename").get_project(pid)["archived"] is False
    at.button(key=f"project-pencil-{pid}").click().run(timeout=120)
    at.button(key=f"project-archive-{pid}").click().run(timeout=120)
    at.button(key="project-archive-confirm").click().run(timeout=120)
    assert not at.exception
    assert f"project-{pid}" not in _labels(at)


def test_context_editor_visibility(polish_env, monkeypatch):
    _use_user(monkeypatch, "pol-ctx")
    pid = UserStore("pol-ctx").create_project("Site")["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    with pytest.raises(KeyError):
        at.text_area(key="project-context-box")
    with pytest.raises(KeyError):
        at.button(key="project-context-save")
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert at.text_area(key="project-context-box").value == ""
    assert "No project context yet." in _text(at)
    assert "Context" in _text(at)


def test_project_empty_states(polish_env, monkeypatch):
    _use_user(monkeypatch, "pol-empty")
    pid = UserStore("pol-empty").create_project("Empty")["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "b" * 16, "title": "Plain",
         "messages": [{"role": "user", "content": "q"}]},
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    body = _text(at)
    assert "No conversations in" in body
    assert "will belong to it" in body
    at.button(key="nav-files").click().run(timeout=120)
    assert "No files in this project yet." in _text(at)
    at.button(key="nav-artifacts").click().run(timeout=120)
    assert "No generated files in this project yet." in _text(at)
    at.button(key="nav-sources").click().run(timeout=120)
    assert "No web sources in this project yet." in _text(at)
    at.button(key="back-to-chat").click().run(timeout=120)
    assert "No project context yet." in _text(at)


def test_scoped_visibility_smoke(polish_env, monkeypatch):
    _use_user(monkeypatch, "pol-scope")
    pid = UserStore("pol-scope").create_project("Site")["id"]
    from services.files import FileStore

    seeded = FileStore("pol-scope").save_upload(b"%PDF-1.4\n%\n", "scoped.pdf")
    _stub_app_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = []
    at.session_state.chats = [
        {"id": "c" * 16, "title": "T", "project_id": pid,
         "messages": [{"role": "user", "content": "q",
                       "attachments": [{"id": seeded.id, "kind": "pdf",
                                        "name": "scoped.pdf"}]}]},
    ]
    at.run(timeout=120)
    at.button(key=f"project-{pid}").click().run(timeout=120)
    assert not at.exception
    at.button(key="nav-files").click().run(timeout=120)
    assert "scoped.pdf" in _text(at)


def test_long_names_render_full_label(polish_env, monkeypatch):
    _use_user(monkeypatch, "pol-long")
    pid = UserStore("pol-long").create_project("n" * 60)["id"]
    _stub_app_agent(monkeypatch)
    at = _run_app()
    labels = _labels(at)
    assert labels.get(f"project-{pid}") == "n" * 34
    import ui.theme as theme

    assert "text-overflow: ellipsis" in theme.THEME_CSS


def test_row_icon_and_save_css_present():
    import ui.theme as theme

    css = theme.THEME_CSS
    assert 'st-key-project-personal button::before' in css
    assert 'st-key-project-' in css and 'currentColor' in css
    assert '.st-key-project-context-save button' in css
    assert 'var(--accent)' in css
    # No duplicate project-disabled rules.
    assert css.count("box-shadow: inset 2px 0 0 var(--accent)") == 1
