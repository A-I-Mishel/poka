"""Phase 7D visual consolidation: hierarchy, density, and contract checks.

Behavioral/structural only — no pixel tests. Verifies the cleanup kept
every capability reachable under stable widget keys.
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


# ------------------------------------------------- Secondary sections unboxed

def test_files_section_unboxed():
    assert "section-label\">Files" in _sidebar_src()


def test_artifacts_section_present_with_compact_rows():
    src = _sidebar_src()
    assert "section-label\">Artifacts" in src
    assert "_artifact_card_html" in src


def test_sources_section_secondary():
    assert "section-label\">Sources" in _sidebar_src()


def test_stats_section_deemphasized():
    src = _sidebar_src()
    assert "section-label\">Stats" in src
    # Stats body is plain compact typography, not a card grid.
    assert "stats-box" in src


def test_research_section_present():
    assert "section-label\">Research" in _sidebar_src()


# ------------------------------------------------- Memory condensed, intact

def test_memory_summary_and_disclosure():
    # 7F: Memory lives in the main workspace behind nav-memory.
    src = _sidebar_src()
    assert "nav-memory" in src
    assert "Remembered facts" in src


def test_memory_controls_still_present():
    src = _sidebar_src()
    for key in ("memory-box", "save-memory", "forget-box", "forget-memory"):
        assert f'"{key}"' in src or f"'{key}'" in src, key


# ------------------------------------------------- Workflows readable

def test_workflow_options_present():
    src = _sidebar_src()
    assert '"workflow-select-research"' in src
    assert '"workflow-select-docs"' in src


def test_workflow_names_not_truncated_by_layout():
    # Stacked full-width rows (no side-by-side option columns).
    src = _sidebar_src()
    assert "_wf_research_col" not in src and "_wf_docs_col" not in src


def test_workflow_actions_present():
    src = _sidebar_src()
    for key in ("workflow-research-run", "workflow-docs-summarize",
                "workflow-docs-findings", "workflow-docs-compare",
                "workflow-exit"):
        assert key in src, key


# ------------------------------------------------- Theme hierarchy/density

def test_section_labels_muted():
    css = _theme_css()
    assert "letter-spacing: 0.05em" in css


def test_sidebar_denser_but_usable():
    css = _theme_css()
    assert "width: 264px" in css
    assert "min-height: 36px" in css


def test_home_cards_lighter():
    css = _theme_css()
    assert "background: transparent" in css


def test_user_message_lighter():
    css = _theme_css()
    assert ':has(div[data-testid="stChatMessageAvatarUser"])' in css
    assert "background: var(--bg-2)" in css


def test_followups_subordinate():
    css = _theme_css()
    assert ".st-key-followups" in css


def test_responsive_rules_present():
    css = _theme_css()
    assert "@media (max-width: 480px)" in css
    assert "st-key-workflow-" in css


# ------------------------------------------------- Contracts unchanged

def _app_src():
    with open(APP_PATH, encoding="utf-8") as fh:
        return fh.read()


def test_widget_keys_stable():
    src = _sidebar_src()
    for key in ("project-personal", "project-create",
                "new-chat", "chat-search", "memory-box", "save-memory",
                "forget-box", "forget-memory", "export-chat", "clean-files",
                "research-close", "conv-move-open"):
        assert key in src, key
    # 7G: Fast/Deep lives inside the composer bar as one toggle pill.
    import ui.composer as composer_mod
    _composer_src = inspect.getsource(composer_mod.render_composer)
    assert "composer-mode" in _composer_src and "deep_mode" in _composer_src


def test_no_new_product_state():
    src = _sidebar_src()
    assert "selected_workflow" in src  # 7A transient state only
    assert "WorkflowNode" not in src and "WorkflowGraph" not in src


def test_escaping_preserved():
    src = _sidebar_src()
    assert "html.escape" in src


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


def _all_text(at):
    parts = [str(m.value) for m in at.markdown]
    try:
        parts += [str(c.value) for c in at.caption]
    except Exception:
        pass
    return " ".join(parts)


def _buttons(at):
    return {str(b.key): str(b.label) for b in at.button}


def test_A_home_renders(apptest_env, monkeypatch):
    _use_user(monkeypatch, "v7a")
    _stub_agent(monkeypatch)
    at = _run_app()
    body = _md(at)
    assert "What can I help with?" in body
    keys = _buttons(at)
    assert keys.get("suggest-0") == "Create"
    assert "composer_send" in keys


def test_B_normal_chat(apptest_env, monkeypatch):
    _use_user(monkeypatch, "v7b")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.text_input(key="composer_input_0").set_value("hello").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception
    assert any(m.get("role") == "assistant" for m in at.session_state.messages)


def test_C_research_launch(apptest_env, monkeypatch):
    _use_user(monkeypatch, "v7c")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-workflows").click().run(timeout=120)
    at.button(key="workflow-select-research").click().run(timeout=120)
    assert not at.exception
    assert "What would you like to research?" in _all_text(at)
    assert at.button(key="workflow-select-research").disabled is True


def test_D_docs_launch(apptest_env, monkeypatch):
    _use_user(monkeypatch, "v7d")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-workflows").click().run(timeout=120)
    at.button(key="workflow-select-docs").click().run(timeout=120)
    assert not at.exception
    assert "No files attached" in _all_text(at)


def test_E_research_workspace(apptest_env, monkeypatch):
    _use_user(monkeypatch, "v7e")
    UserStore("v7e").create_brief(
        "mars news?",
        [{"title": "Mars News", "url": "https://example.com/mars",
          "domain": "example.com"}],
        "Mars summary.")
    bid = UserStore("v7e").list_briefs()[0]["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-research").click().run(timeout=120)
    at.button(key=f"research-open-{bid}").click().run(timeout=120)
    assert not at.exception
    assert "mars news?" in _md(at)


def test_F_gallery(apptest_env, monkeypatch):
    _use_user(monkeypatch, "v7f")
    FileStore("v7f").register_output("Old.docx", b"PK\x03\x04x", "docx")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-artifacts").click().run(timeout=120)
    assert "Old.docx" in _md(at)
    assert any(str(b.key).startswith("side-dl-") for b in at.download_button)


def test_G_memory_controls(apptest_env, monkeypatch):
    _use_user(monkeypatch, "v7g")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-memory").click().run(timeout=120)
    at.text_area(key="memory-box").set_value("Prefers concise answers").run(timeout=60)
    at.button(key="save-memory").click().run(timeout=120)
    assert not at.exception
    assert UserStore("v7g").load_notes() == "Prefers concise answers"


def test_H_projects(apptest_env, monkeypatch):
    _use_user(monkeypatch, "v7h")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="project-create").click().run(timeout=120)
    at.text_input(key="project-name-box").set_value("Website").run(timeout=60)
    at.button(key="project-create-save").click().run(timeout=120)
    assert not at.exception
    assert UserStore("v7h").list_projects()[0]["name"] == "Website"


def test_I_workflow_options_stacked():
    # Narrow-layout rule keeps both full names readable when stacked.
    css = _theme_css()
    assert "st-key-workflow-" in css
    src = _sidebar_src()
    assert "Document Analysis" in src
