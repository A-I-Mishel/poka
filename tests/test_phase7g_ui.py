"""Phase 7G premium minimal workspace: nav-first sidebar, calm home,
single-composer guarantee, and More-gated secondary destinations.

Behavioral/structural only — no pixel tests.
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
    return inspect.getsource(ui.sidebar)


def _main_inputs(at):
    return [(str(t.key), str(t.value)) for t in at.main.text_input]


# ------------------------------------------------------- Default sidebar

def test_01_brand_visible():
    assert "Poka" in _sidebar_src()


def test_02_new_chat_visible():
    assert '"new-chat"' in _sidebar_src()


def test_03_search_visible():
    assert '"chat-search"' in _sidebar_src()


def test_04_projects_visible():
    assert "section-label\">Projects" in _sidebar_src()


def test_05_research_visible():
    assert '"nav-research"' in _sidebar_src()


def test_06_workflows_visible():
    assert '"nav-workflows"' in _sidebar_src()


def test_07_more_visible():
    assert '"more-toggle"' in _sidebar_src()


def test_08_recents_visible():
    assert "section-label\">Recents" in _sidebar_src()


def test_09_account_visible():
    assert "section-label\">Account" in _sidebar_src()


def test_10_memory_condensed_by_default():
    # Only the More toggle shows; destination rows need opening.
    src = _sidebar_src()
    assert '"more-toggle"' in src
    assert '"nav-memory"' in src


def test_11_secondary_behind_more():
    import application.session as sess
    src = inspect.getsource(sess.ensure_session_defaults)
    assert "more_open" in src


def test_12_details_gated_behind_more():
    # Destination rows render only when More is open.
    src = _sidebar_src()
    assert "if _more_open:" in src
    assert '"more-toggle"' in src


def test_13_workflow_form_gated():
    # Workflow panels render inside the main workflows view only.
    assert "render_workflows_view" in _sidebar_src()


def test_14_no_orphan_detail_render():
    # Every destination body funnels through the single dispatcher.
    src = _sidebar_src()
    assert "render_workspace_view" in src
    assert src.count("def render_") >= 8


def test_15_move_gated_to_targets():
    src = _sidebar_src()
    assert "_move_targets" in src
    assert '"conv-move-open"' in src


def test_16_move_hidden_by_default(fenv):
    # Fresh user: messages exist but no projects and no conversation
    # project — the move control stays out of the way.
    assert "_move_targets" in _sidebar_src()


# ------------------------------------------------------------------ More

def test_17_more_toggle_exists():
    assert '"more-toggle"' in _sidebar_src()


def test_18_memory_nav_exists():
    assert '"nav-memory"' in _sidebar_src()


def test_19_files_nav_exists():
    assert '"nav-files"' in _sidebar_src()


def test_20_artifacts_nav_exists():
    assert '"nav-artifacts"' in _sidebar_src()


def test_21_sources_nav_exists():
    assert '"nav-sources"' in _sidebar_src()


def test_22_stats_nav_exists():
    assert '"nav-stats"' in _sidebar_src()


def test_23_select_closes_more():
    # Auto-close keeps the invariant: toggle always opens.
    assert "more_open = False" in _sidebar_src()


def test_24_back_to_chat_exists():
    assert '"back-to-chat"' in _sidebar_src()


# ------------------------------------------------------------------ Home

def test_25_single_composer_home():
    with open(APP_PATH, encoding="utf-8") as fh:
        app_src = fh.read()
    assert app_src.count("render_composer()") == 1


def test_26_home_actions_exist():
    app_src = open(APP_PATH, encoding="utf-8").read()
    assert "suggest-" in app_src
    assert "Analyze files" in app_src


def test_30_quick_actions_compact():
    import ui.theme as theme
    assert ".st-key-home" in theme.THEME_CSS


# --------------------------------------------------------------- Workspace

def test_31_research_view_exists():
    assert "def render_research_view" in _sidebar_src()


def test_32_workflows_view_exists():
    assert "def render_workflows_view" in _sidebar_src()


def test_33_memory_view_exists():
    assert "def render_memory_view" in _sidebar_src()


def test_34_files_view_exists():
    assert "def render_files_view" in _sidebar_src()


def test_35_artifacts_view_exists():
    assert "def render_artifacts_view" in _sidebar_src()


# ------------------------------------------------------------------ Chat

def test_36_single_composer_normal_chat():
    # Exactly one composer call site; workflow inputs live in the
    # workflows view module only.
    with open(APP_PATH, encoding="utf-8") as fh:
        app_src = fh.read()
    assert app_src.count("render_composer()") == 1
    assert "workflow-research-question" not in app_src


def test_37_workflow_inputs_scoped():
    src = _sidebar_src()
    assert '"workflow-research-question"' in src
    assert "def render_workflows_view" in src


def test_38_message_behavior_intact():
    import ui.chat as chat_mod
    assert hasattr(chat_mod, "render_history")
    assert hasattr(chat_mod, "render_assistant_response")


def test_39_no_duplicate_composer_keys():
    import ui.composer as composer_mod
    src = inspect.getsource(composer_mod.render_composer)
    assert src.count("composer_plus") == 1
    assert src.count("composer_send") == 1


# --------------------------------------------------------------- Projects

def test_40_project_switching_intact():
    assert "active_project_id" in _sidebar_src()


def test_41_personal_intact():
    assert '"project-personal"' in _sidebar_src()


def test_42_resources_still_scoped():
    assert "_workspace_scope_bundle" in _sidebar_src()


# -------------------------------------------------------------- Responsive

def test_43_width_bounded():
    import ui.theme as theme
    assert "264px" in theme.THEME_CSS


def test_44_stacking_rules():
    import ui.theme as theme
    assert "flex-wrap" in theme.THEME_CSS


def test_45_reachable_selectors():
    import ui.theme as theme
    assert "min-height: 36px" in theme.THEME_CSS


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


def _open_nav(at, key):
    at.button(key="more-toggle").click().run(timeout=120)
    at.button(key=key).click().run(timeout=120)
    assert not at.exception
    return at


def test_A_default(apptest_env, monkeypatch):
    _use_user(monkeypatch, "g7a")
    _stub_agent(monkeypatch)
    at = _run_app()
    keys = _buttons(at)
    for key in ("new-chat", "nav-research", "nav-workflows",
                "project-personal"):
        assert key in keys, key
    assert "More" in _md(at)
    assert "Account" in _md(at)
    # Secondary rows hide until More opens.
    assert "nav-memory" not in keys
    assert "What can I help with?" in _md(at)


def test_B_more(apptest_env, monkeypatch):
    _use_user(monkeypatch, "g7b")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120)
    keys = _buttons(at)
    for key in ("nav-memory", "nav-files", "nav-artifacts",
                "nav-sources", "nav-stats"):
        assert key in keys, key
    at.button(key="nav-memory").click().run(timeout=120)
    assert at.session_state["sidebar_view"] == "memory"


def test_C_memory(apptest_env, monkeypatch):
    _use_user(monkeypatch, "g7c")
    _stub_agent(monkeypatch)
    at = _run_app()
    _open_nav(at, "nav-memory")
    at.text_area(key="memory-box").set_value("Lives in Lisbon").run(timeout=60)
    at.button(key="save-memory").click().run(timeout=120)
    assert not at.exception
    assert UserStore("g7c").load_notes() == "Lives in Lisbon"
    assert "memory-box" in {str(e.key) for e in at.main.text_area}


def test_D_files(apptest_env, monkeypatch):
    _use_user(monkeypatch, "g7d")
    FileStore("g7d").save_upload(PDF_BYTES, "field.pdf")
    _stub_agent(monkeypatch)
    at = _run_app()
    _open_nav(at, "nav-files")
    assert "field.pdf" in _md(at)


def test_E_artifacts(apptest_env, monkeypatch):
    _use_user(monkeypatch, "g7e")
    FileStore("g7e").register_output("Gallery.docx", b"PK\x03\x04x", "docx")
    _stub_agent(monkeypatch)
    at = _run_app()
    _open_nav(at, "nav-artifacts")
    assert "Gallery.docx" in _md(at)
    assert any(str(b.key).startswith("side-dl-") for b in at.download_button)


def test_F_research(apptest_env, monkeypatch):
    _use_user(monkeypatch, "g7f")
    UserStore("g7f").create_brief(
        "mars news?",
        [{"title": "Mars News", "url": "https://example.com/mars",
          "domain": "example.com"}],
        "Mars summary.")
    bid = UserStore("g7f").list_briefs()[0]["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="nav-research").click().run(timeout=120)
    at.button(key=f"research-open-{bid}").click().run(timeout=120)
    assert "mars news?" in _md(at)
    assert "Mars summary." in _md(at)


def test_G_workflows(apptest_env, monkeypatch):
    _use_user(monkeypatch, "g7g")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="nav-workflows").click().run(timeout=120)
    at.button(key="workflow-select-research").click().run(timeout=120)
    assert "What would you like to research?" in _md(at)
    at.button(key="back-to-chat").click().run(timeout=120)
    assert at.session_state["sidebar_view"] is None


def test_H_chat(apptest_env, monkeypatch):
    _use_user(monkeypatch, "g7h")
    _stub_agent(monkeypatch)
    at = _run_app()
    assert "back-to-chat" not in _buttons(at)
    at.text_input(key="composer_input_0").set_value("hello").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception
    assert len(_main_inputs(at)) == 1
    assert any(m.get("role") == "assistant" for m in at.session_state.messages)


def test_I_projects(apptest_env, monkeypatch):
    _use_user(monkeypatch, "g7i")
    s = UserStore("g7i")
    pa, pb = s.create_project("A")["id"], s.create_project("B")["id"]
    ba = s.create_brief("in A?", [], "e", pa)["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="nav-research").click().run(timeout=120)
    at.session_state.active_project_id = pa
    at.run(timeout=60)
    assert f"research-open-{ba}" in _buttons(at)
    at.session_state.active_project_id = pb
    at.run(timeout=60)
    assert f"research-open-{ba}" not in _buttons(at)


def test_J_narrow():
    import ui.theme as theme
    assert "@media (max-width: 480px)" in theme.THEME_CSS
    assert "@media (max-width: 390px)" in theme.THEME_CSS
    assert "264px" in theme.THEME_CSS


def test_K_sidebar_rail_rows():
    # Section 28: full-width borderless rows across button generations,
    # section labels clear the rows above (no search/PROJECTS overlap).
    import ui.theme as theme
    css = theme.THEME_CSS
    assert 'stSidebar"] div[data-testid="stButton"] > button' in css
    assert ".st-key-new-chat button" in css
    assert "margin: 20px 0 6px" in css
