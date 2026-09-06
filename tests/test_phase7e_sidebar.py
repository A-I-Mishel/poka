"""Phase 7E navigation restructure: nav surface + More destinations.

Behavioral/structural only — no pixel tests. Verifies every capability
stays reachable under stable keys while secondary bodies sit behind
compact navigation.
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
    # Module source: 7F renders destinations from main-area views defined
    # in this same module, so contract strings live here regardless of
    # sidebar-vs-main placement.
    return inspect.getsource(ui.sidebar)


def _theme_css():
    import ui.theme as theme
    return theme.THEME_CSS


# ------------------------------------------------------- Navigation structure

def test_01_new_chat_accessible():
    assert '"new-chat"' in _sidebar_src()


def test_02_search_accessible():
    assert '"chat-search"' in _sidebar_src()


def test_03_projects_visible():
    src = _sidebar_src()
    assert "section-label\">Projects" in src
    assert '"project-personal"' in src and '"project-create"' in src


def test_04_research_navigation_exists():
    assert "section-label\">Research" in _sidebar_src()


def test_05_workflows_navigation_exists():
    src = _sidebar_src()
    assert '"workflow-select-research"' in src
    assert '"workflow-select-docs"' in src


def test_06_more_exists():
    src = _sidebar_src()
    assert "section-label\">More" in src
    assert ">More</p>" in src


def test_07_account_accessible():
    src = _sidebar_src()
    assert "section-label\">Account" in src
    assert '"export-chat"' in src and '"clean-files"' in src


def test_08_secondary_behind_navigation():
    src = _sidebar_src()
    # Destination bodies render inside nav-driven expanders, collapsed
    # unless their sidebar_view is selected.
    for dest in ("memory", "files", "artifacts", "sources", "stats"):
        assert f'_sidebar_view == "{dest}"' in src, dest


def test_09_more_reveals_memory():
    assert '"nav-memory"' in _sidebar_src()


def test_10_more_reveals_files():
    assert '"nav-files"' in _sidebar_src()


def test_11_more_reveals_artifacts():
    assert '"nav-artifacts"' in _sidebar_src()


def test_12_more_reveals_sources():
    assert '"nav-sources"' in _sidebar_src()


def test_13_more_reveals_stats():
    assert '"nav-stats"' in _sidebar_src()


# ------------------------------------------------------------------- Memory

def test_14_memory_controls_reachable():
    src = _sidebar_src()
    for key in ("memory-box", "save-memory", "forget-box", "forget-memory"):
        assert key in src, key


def test_15_save_memory_logic_intact():
    src = _sidebar_src()
    assert "save_notes" in src and "Memory saved" in src


def test_16_facts_accessible():
    assert "_vault_rows" in _sidebar_src()


def test_17_forget_accessible():
    assert "delete_memory_fact" in _sidebar_src()


# -------------------------------------------------------------------- Files

def test_18_files_view_reachable():
    assert "_upload_row_html" in _sidebar_src()


def test_19_upload_guidance_intact():
    assert "No uploaded files yet" in _sidebar_src()


def test_20_existing_files_render():
    assert "list_uploads" in _sidebar_src()


# ---------------------------------------------------------------- Artifacts

def test_21_gallery_reachable():
    assert "_artifact_card_html" in _sidebar_src()


def test_22_download_available():
    src = _sidebar_src()
    assert "side-dl-" in src and "read_output" in src


def test_23_regenerate_where_valid():
    src = _sidebar_src()
    assert "can_regenerate" in src and "regen-side-" in src


# ----------------------------------------------------------------- Research

def test_24_workspace_opens():
    assert "visible_briefs_for_scope" in _sidebar_src()


def test_25_brief_selection_intact():
    assert "selected_brief_id" in _sidebar_src()


def test_26_project_scope_intact():
    assert "is_brief_in_scope" in _sidebar_src()


def test_27_personal_scope_intact():
    assert "In Personal" in _sidebar_src()


# ---------------------------------------------------------------- Workflows

def test_28_chooser_intact():
    assert "get_selected_workflow" in _sidebar_src()


def test_29_research_workflow_intact():
    assert "workflow-research-run" in _sidebar_src()


def test_30_docs_workflow_intact():
    assert "workflow-docs-summarize" in _sidebar_src()


def test_31_continue_in_chat_intact():
    assert "exit_workflow" in _sidebar_src()


# ----------------------------------------------------------------- Projects

def test_32_switching_intact():
    assert "active_project_id" in _sidebar_src()


def test_33_creation_intact():
    assert "create_project" in _sidebar_src()


def test_34_rename_archive_intact():
    src = _sidebar_src()
    assert "rename_project" in src and "archive_project" in src


# ------------------------------------------------------- Navigation safety

def test_35_view_state_minimal():
    src = _sidebar_src()
    assert "sidebar_view" in src
    assert "WorkflowNode" not in src and "WorkflowGraph" not in src


def test_36_view_switch_safe():
    import application.session as sess
    src = inspect.getsource(sess.ensure_session_defaults)
    assert "sidebar_view" in src


def test_37_user_switch_clears_view():
    # Same wipe mechanism as every other user-scoped key.
    import application.session as sess
    src = inspect.getsource(sess.ensure_session_defaults)
    assert "_bound_user_id" in src and "del st.session_state" in src


def test_38_foreign_ids_still_blocked(fenv):
    UserStore("alice").create_brief("q", [], "")
    alice_id = UserStore("alice").list_briefs()[0]["id"]
    assert UserStore("bob").get_brief(alice_id) is None
    FileStore("alice").register_output("a.docx", b"0123456789", "docx")
    alice_oid = FileStore("alice").list_outputs()[0].id
    assert FileStore("bob").get_output(alice_oid) is None


# --------------------------------------------------------------- Responsive

def test_39_responsive_css_exists():
    css = _theme_css()
    assert "@media (max-width: 480px)" in css
    assert "@media (max-width: 390px)" in css


def test_40_nav_styling_compact():
    css = _theme_css()
    assert "stSidebar" in css and "details" in css


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


def _buttons(at):
    return {str(b.key): str(b.label) for b in at.button}


def test_A_default_sidebar(apptest_env, monkeypatch):
    _use_user(monkeypatch, "n7a")
    _stub_agent(monkeypatch)
    at = _run_app()
    keys = _buttons(at)
    for key in ("new-chat", "nav-research", "nav-workflows",
                "project-personal", "project-create"):
        assert key in keys, key
    assert "More" in _md(at)
    # 7F: destinations render in the main workspace only when selected —
    # default sidebar carries navigation rows, not detail bodies.
    for key in ("memory-box", "workflow-select-research",
                "workflow-select-docs", "nav-memory"):
        assert key not in keys, key
    assert "more-toggle" in keys
    assert len(at.expander) == 0


def test_B_more_reveals(apptest_env, monkeypatch):
    _use_user(monkeypatch, "n7b")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120)
    keys = _buttons(at)
    for key in ("nav-memory", "nav-files", "nav-artifacts", "nav-sources", "nav-stats"):
        assert key in keys, key
    at.button(key="nav-files").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["sidebar_view"] == "files"


def test_C_memory(apptest_env, monkeypatch):
    _use_user(monkeypatch, "n7c")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-memory").click().run(timeout=120)
    at.text_area(key="memory-box").set_value("Prefers concise answers").run(timeout=60)
    at.button(key="save-memory").click().run(timeout=120)
    assert not at.exception
    assert UserStore("n7c").load_notes() == "Prefers concise answers"


def test_D_research(apptest_env, monkeypatch):
    _use_user(monkeypatch, "n7d")
    UserStore("n7d").create_brief(
        "mars news?",
        [{"title": "Mars News", "url": "https://example.com/mars",
          "domain": "example.com"}],
        "Mars summary.")
    bid = UserStore("n7d").list_briefs()[0]["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-research").click().run(timeout=120)
    at.button(key=f"research-open-{bid}").click().run(timeout=120)
    assert not at.exception
    assert "mars news?" in _md(at)


def test_E_workflows(apptest_env, monkeypatch):
    _use_user(monkeypatch, "n7e")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-workflows").click().run(timeout=120)
    at.button(key="workflow-select-research").click().run(timeout=120)
    assert at.session_state["selected_workflow"] == "research"
    at.button(key="workflow-exit").click().run(timeout=120)
    at.button(key="workflow-select-docs").click().run(timeout=120)
    assert at.session_state["selected_workflow"] == "doc_analysis"


def test_F_projects(apptest_env, monkeypatch):
    _use_user(monkeypatch, "n7f")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="project-create").click().run(timeout=120)
    at.text_input(key="project-name-box").set_value("Website").run(timeout=60)
    at.button(key="project-create-save").click().run(timeout=120)
    assert not at.exception
    pid = UserStore("n7f").list_projects()[0]["id"]
    assert at.session_state["active_project_id"] == pid


def test_G_recents(apptest_env, monkeypatch):
    _use_user(monkeypatch, "n7g")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.session_state.chats = [
        {"id": "b" * 16, "title": "Old chat",
         "messages": [{"role": "user", "content": "old"}]}]
    at.run(timeout=60)
    at.button(key="hist-0").click().run(timeout=120)
    assert not at.exception
    assert at.session_state.messages[0]["content"] == "old"


def test_H_account(apptest_env, monkeypatch):
    _use_user(monkeypatch, "n7h")
    _stub_agent(monkeypatch)
    at = _run_app()
    assert "Account" in _md(at)
    keys = _buttons(at)
    assert "clean-files" in keys
    at.session_state.messages = [{"role": "user", "content": "hi"}]
    at.run(timeout=60)
    assert any(str(b.key) == "export-chat" for b in at.download_button)


def test_I_chat(apptest_env, monkeypatch):
    _use_user(monkeypatch, "n7i")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-files").click().run(timeout=120)
    at.text_input(key="composer_input_0").set_value("hello").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception
    assert any(m.get("role") == "assistant" for m in at.session_state.messages)


def test_J_narrow_structure():
    css = _theme_css()
    assert "264px" in css
    assert "flex-wrap" in css
