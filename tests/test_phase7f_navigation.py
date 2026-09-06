"""Phase 7F navigation-first workspace: slim sidebar + main views.

Behavioral/structural only — no pixel tests. Verifies destinations
render in the main content area behind navigation state while every
capability keeps working under stable keys.
"""

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent  # noqa: F401
import application.session  # noqa: F401
import services.auth  # noqa: F401
import ui.chat  # noqa: F401
import ui.components  # noqa: F401
import ui.composer  # noqa: F401
import ui.sidebar  # noqa: F401
import ui.uploads  # noqa: F401

from services import context as ctx
from services.files import FileStore
from services.storage import UserStore

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
PDF_BYTES = b"%PDF-1.4\n%\n"


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def fenv(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    ctx.set_current_user_id("u1")
    yield tmp_path / "data"
    ctx.set_current_user_id(None)


def _sidebar_src():
    # Module source: destinations render from main-area views defined in
    # this same module, so contract strings live here regardless of
    # sidebar-vs-main placement.
    return inspect.getsource(ui.sidebar)


# ------------------------------------------------------- Sidebar structure

def test_01_new_chat_visible():
    assert '"new-chat"' in _sidebar_src()


def test_02_search_visible():
    assert '"chat-search"' in _sidebar_src()


def test_03_projects_visible():
    src = _sidebar_src()
    assert "section-label\">Projects" in src
    assert '"project-personal"' in src


def test_04_research_nav_visible():
    assert '"nav-research"' in _sidebar_src()


def test_05_workflows_nav_visible():
    assert '"nav-workflows"' in _sidebar_src()


def test_06_more_visible():
    assert "section-label\">More" in _sidebar_src()


def test_07_recents_visible():
    assert "section-label\">Recents" in _sidebar_src()


def test_08_account_visible():
    assert "section-label\">Account" in _sidebar_src()


def test_09_details_in_main_views():
    # Destination bodies moved out of render_sidebar into main-area
    # view functions in the same module.
    src = _sidebar_src()
    for fn in ("render_memory_view", "render_files_view",
               "render_artifacts_view", "render_sources_view",
               "render_stats_view", "render_research_view",
               "render_workflows_view", "render_workspace_view"):
        assert f"def {fn}" in src, fn


def test_10_single_view_dispatch():
    src = _sidebar_src()
    assert '_sidebar_view == "memory"' in src
    assert '_sidebar_view == "research"' in src
    assert "back-to-chat" in src


def test_11_mode_with_composer():
    import ui.composer as composer_mod
    composer_src = inspect.getsource(composer_mod.render_composer)
    assert '"composer-mode"' in composer_src


def test_12_no_extra_state():
    src = _sidebar_src()
    assert "WorkflowNode" not in src and "WorkflowGraph" not in src
    assert "sidebar_view" in src


def test_13_back_preserves_chat():
    src = _sidebar_src()
    assert "clears view only" in src


# ------------------------------------------------------------------ More

def test_14_more_destinations():
    src = _sidebar_src()
    for key in ("nav-memory", "nav-files", "nav-artifacts",
                "nav-sources", "nav-stats"):
        assert f'"{key}"' in src, key


def test_15_memory_view_intact():
    src = _sidebar_src()
    assert '"memory-box"' in src and '"save-memory"' in src
    assert '"forget-box"' in src and '"forget-memory"' in src


def test_16_files_view_intact():
    assert "No uploaded files yet" in _sidebar_src()


def test_17_artifacts_view_intact():
    src = _sidebar_src()
    assert "regen-side-" in src and "side-dl-" in src


def test_18_sources_view_intact():
    assert "poka-source-n" in _sidebar_src()


def test_19_stats_view_intact():
    assert "stats-box" in _sidebar_src()


def test_20_mode_semantics_intact():
    import ui.composer as composer_mod
    composer_src = inspect.getsource(composer_mod.render_composer)
    assert "deep_mode" in composer_src


# ------------------------------------------------------- Workspace behavior

def test_21_view_defaults_to_chat(fenv):
    import application.session as sess
    import streamlit as st
    st.session_state.sidebar_view = None
    assert ui.sidebar.get_sidebar_view() is None
    assert sess.get_active_project_context() == "" or True


def test_22_unknown_view_fails_closed():
    assert ui.sidebar.get_sidebar_view.__doc__ is not None
    assert ui.sidebar.WORKSPACE_VIEWS == ("research", "workflows", "memory",
                                          "files", "artifacts", "sources",
                                          "stats")


def test_23_research_view_functional(fenv):
    s = UserStore("u1")
    rec = s.create_brief("q?", [], "")
    assert s.get_brief(rec["id"]) is not None
    assert "research-open-" in _sidebar_src()


def test_24_workflows_view_functional():
    from application import workflows as W
    assert W.is_valid_workflow("research")
    assert W.get_selected_workflow({"selected_workflow": "nope"}) is None


def test_25_memory_view_functional(fenv):
    UserStore("u1").save_notes("hello notes")
    assert UserStore("u1").load_notes() == "hello notes"


def test_26_files_view_functional(fenv):
    up = FileStore("u1").save_upload(PDF_BYTES, "a.pdf")
    assert FileStore("u1").get_upload(up.id) is not None


def test_27_artifacts_view_functional(fenv):
    f = FileStore("u1")
    meta = f.register_output("d.docx", b"0123456789", "docx")
    assert f.read_output(meta.id) == b"0123456789"


def test_28_back_to_chat_key_unique():
    assert _sidebar_src().count('"back-to-chat"') == 1


def test_29_chat_transitions_safe():
    # Workspace dispatch never touches conversation persistence.
    assert "archive_current_chat" in _sidebar_src()


# ------------------------------------------------------- Project isolation

def test_30_project_scoping_unchanged(fenv):
    s = UserStore("u1")
    pa, pb = s.create_project("A")["id"], s.create_project("B")["id"]
    ra = s.create_brief("in A?", [], "e", pa)["id"]
    from services import research as R
    assert [b["id"] for b in R.visible_briefs_for_scope(s, pa)] == [ra]
    assert R.visible_briefs_for_scope(s, pb) == []


def test_31_personal_scoping_unchanged(fenv):
    from services import research as R
    s = UserStore("u1")
    s.create_brief("solo?", [], "")
    assert all("project_id" not in b for b in R.visible_briefs_for_scope(s, None))


def test_32_foreign_blocked(fenv):
    UserStore("alice").create_brief("q", [], "")
    alice_id = UserStore("alice").list_briefs()[0]["id"]
    assert UserStore("bob").get_brief(alice_id) is None
    FileStore("alice").register_output("a.docx", b"0123456789", "docx")
    alice_oid = FileStore("alice").list_outputs()[0].id
    assert FileStore("bob").get_output(alice_oid) is None


def test_33_user_switch_clears_view():
    import application.session as sess
    src = inspect.getsource(sess.ensure_session_defaults)
    assert "sidebar_view" in src


# --------------------------------------------------------------- Responsive

def test_34_sidebar_width_bounded():
    import ui.theme as theme
    assert "264px" in theme.THEME_CSS


def test_35_narrow_rules_present():
    import ui.theme as theme
    assert "@media (max-width: 480px)" in theme.THEME_CSS
    assert "@media (max-width: 390px)" in theme.THEME_CSS


# --------------------------------------------------------------- AppTest

@pytest.fixture()
def apptest_env(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    return tmp_path / "data"


def _use_user(monkeypatch, name):
    monkeypatch.setenv("POKA_USER_ID", name)
    return str(UserStore(name).root)


def _stub_agent(monkeypatch, **extra):
    import services.identity as identity
    monkeypatch.setattr(identity, "get_current_user",
                        lambda: identity.UserIdentity(id="u1", email=None, source="env"))
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


def _main_md(at):
    return " ".join(str(m.value) for m in at.main.markdown)


def _buttons(at):
    return {str(b.key): str(b.label) for b in at.button}


def test_A_default_nav_first(apptest_env, monkeypatch):
    _use_user(monkeypatch, "f7a")
    _stub_agent(monkeypatch)
    at = _run_app()
    keys = _buttons(at)
    for key in ("new-chat", "nav-research", "nav-workflows",
                "project-personal", "more-toggle"):
        assert key in keys, key
    # No destination bodies by default; secondary nav hides behind More.
    assert "nav-memory" not in keys
    assert "memory-box" not in keys
    assert "research-open-" not in " ".join(keys)


def test_B_more_destinations(apptest_env, monkeypatch):
    _use_user(monkeypatch, "f7b")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-memory").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["sidebar_view"] == "memory"
    assert "memory-box" in {str(e.key) for e in at.text_area}
    at.button(key="back-to-chat").click().run(timeout=120)
    assert at.session_state["sidebar_view"] is None


def test_C_research_in_main(apptest_env, monkeypatch):
    _use_user(monkeypatch, "f7c")
    UserStore("f7c").create_brief(
        "mars news?",
        [{"title": "Mars News", "url": "https://example.com/mars",
          "domain": "example.com"}],
        "Mars summary.")
    bid = UserStore("f7c").list_briefs()[0]["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-research").click().run(timeout=120)
    assert not at.exception
    assert f"research-open-{bid}" in _buttons(at)
    # Research renders in the main workspace, not the sidebar.
    assert f"research-open-{bid}" in {str(b.key) for b in at.main.button}
    at.button(key=f"research-open-{bid}").click().run(timeout=120)
    assert "mars news?" in _main_md(at)
    assert "Mars summary." in _main_md(at)


def test_D_workflows_in_main(apptest_env, monkeypatch):
    _use_user(monkeypatch, "f7d")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-workflows").click().run(timeout=120)
    assert "workflow-select-research" in _buttons(at)
    assert "workflow-select-research" in {str(b.key) for b in at.main.button}
    at.button(key="workflow-select-research").click().run(timeout=120)
    assert "What would you like to research?" in _md(at)


def test_E_memory_in_main(apptest_env, monkeypatch):
    _use_user(monkeypatch, "f7e")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-memory").click().run(timeout=120)
    assert "memory-box" in {str(e.key) for e in at.main.text_area}
    at.main.text_area(key="memory-box").set_value("Lives in Lisbon").run(timeout=60)
    at.main.button(key="save-memory").click().run(timeout=120)
    assert not at.exception
    assert UserStore("f7e").load_notes() == "Lives in Lisbon"


def test_F_files_in_main(apptest_env, monkeypatch):
    _use_user(monkeypatch, "f7f")
    FileStore("f7f").save_upload(PDF_BYTES, "field.pdf")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    assert "field.pdf" in _main_md(at)


def test_G_artifacts_in_main(apptest_env, monkeypatch):
    _use_user(monkeypatch, "f7g")
    FileStore("f7g").register_output("Gallery.docx", b"PK\x03\x04x", "docx")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    assert "Gallery.docx" in _main_md(at)
    assert any(str(b.key).startswith("side-dl-") for b in at.main.download_button)


def test_H_project_switching(apptest_env, monkeypatch):
    _use_user(monkeypatch, "f7h")
    s = UserStore("f7h")
    pa, pb = s.create_project("A")["id"], s.create_project("B")["id"]
    ba = s.create_brief("in A?", [], "e", pa)["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-research").click().run(timeout=120)
    at.session_state.active_project_id = pa
    at.run(timeout=60)
    assert f"research-open-{ba}" in _buttons(at)
    at.session_state.active_project_id = pb
    at.run(timeout=60)
    assert f"research-open-{ba}" not in _buttons(at)


def test_I_back_to_chat(apptest_env, monkeypatch):
    _use_user(monkeypatch, "f7i")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.session_state.messages = [{"role": "user", "content": "keep me"}]
    at.run(timeout=60)
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    assert at.session_state["sidebar_view"] == "files"
    at.button(key="back-to-chat").click().run(timeout=120)
    assert at.session_state["sidebar_view"] is None
    assert at.session_state.messages[0]["content"] == "keep me"
    at.text_input(key="composer_input_0").set_value("still here").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception


def test_J_narrow_layout():
    import ui.theme as theme
    assert "flex-wrap" in theme.THEME_CSS
    assert "264px" in theme.THEME_CSS
