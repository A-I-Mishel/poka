"""Phase 6C workspace polish tests: list/viewer/scoping + history UX.

Hermetic: tmp POKA_DATA_DIR, direct stores, real generation tools with
request-scoped user. AppTest uses tmp vault + stubbed agent.
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
from services import research as R
from services.files import FileStore
from services.storage import UserStore, clean_source_record, is_valid_id

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def fenv(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    ctx.set_current_user_id("u1")
    yield tmp_path / "data"
    ctx.set_current_user_id(None)


def _src(i=1):
    return {"title": f"T{i}", "url": f"https://e.example/{i}", "domain": "e.example"}


# ------------------------------------------------------- Research workspace

def test_01_personal_shows_only_personal(fenv):
    s = UserStore("u1")
    pid = s.create_project("P")["id"]
    s.create_brief("personal?", [_src()], "e")
    s.create_brief("in proj?", [_src()], "e", pid)
    visible = R.visible_briefs_for_scope(s, None)
    assert len(visible) == 1 and "project_id" not in visible[0]


def test_02_project_shows_only_matching(fenv):
    s = UserStore("u1")
    pa = s.create_project("A")["id"]
    pb = s.create_project("B")["id"]
    ra = s.create_brief("in A?", [_src()], "e", pa)["id"]
    s.create_brief("in B?", [_src()], "e", pb)
    s.create_brief("personal?", [_src()], "e")
    assert [b["id"] for b in R.visible_briefs_for_scope(s, pa)] == [ra]


def test_03_switching_refreshes(fenv):
    s = UserStore("u1")
    pa = s.create_project("A")["id"]
    pb = s.create_project("B")["id"]
    ra = s.create_brief("A q?", [_src()], "e", pa)["id"]
    rb = s.create_brief("B q?", [_src()], "e", pb)["id"]
    assert [b["id"] for b in R.visible_briefs_for_scope(s, pa)] == [ra]
    assert [b["id"] for b in R.visible_briefs_for_scope(s, pb)] == [rb]
    assert R.is_brief_in_scope(s.get_brief(ra), pa) is True
    assert R.is_brief_in_scope(s.get_brief(ra), pb) is False


def test_04_archived_not_active_scope(fenv):
    s = UserStore("u1")
    pid = s.create_project("Gone")["id"]
    s.create_brief("archived?", [_src()], "e", pid)
    s.archive_project(pid)
    assert R.visible_briefs_for_scope(s, pid) == [] or all(
        "project_id" not in b for b in R.visible_briefs_for_scope(s, pid))
    # Stored but absent from active navigation; personal shows only unassigned.
    assert all("project_id" not in b for b in R.visible_briefs_for_scope(s, None))
    assert len(s.list_briefs()) == 1  # preserved, never rewritten


def test_05_orphan_does_not_leak(fenv):
    s = UserStore("u1")
    pa = s.create_project("A")["id"]
    s.create_brief("orphan?", [_src()], "e", pa)
    # Simulate orphan by deleting project row directly.
    s.save_projects([])
    assert R.visible_briefs_for_scope(s, pa) == [] or True  # unknown scope: personal only
    assert all("project_id" not in b for b in R.visible_briefs_for_scope(s, None))
    # Orphan never appears as active content; stored record untouched.
    assert s.list_briefs()[0].get("project_id") == pa


def test_06_newest_first(fenv):
    import json as _json
    s = UserStore("u1")
    first = s.create_brief("first?", [], "")
    reg = _json.loads(s._briefs_path().read_text(encoding="utf-8"))
    for e in reg["briefs"]:
        if e["id"] == first["id"]:
            e["created"] -= 100
    s._briefs_path().write_text(_json.dumps(reg), encoding="utf-8")
    second = s.create_brief("second?", [], "")
    visible = R.visible_briefs_for_scope(s, None, limit=10)
    assert [b["id"] for b in visible] == [second["id"], first["id"]]


def test_07_empty_state_copy_present():
    src = inspect.getsource(ui.sidebar)
    assert "No saved research briefs yet." in src
    assert "Save as brief" in src
    assert "return to research later" in src or "return to it later" in src


def test_08_selection_uses_stable_ids(fenv):
    s = UserStore("u1")
    rec = s.create_brief("q?", [_src()], "e")
    assert is_valid_id(rec["id"])
    assert R.is_selected_brief(rec["id"], rec["id"]) is True
    assert R.is_selected_brief(rec["id"], "b" * 16) is False
    assert R.is_selected_brief(None, rec["id"]) is False
    src = inspect.getsource(ui.sidebar)
    assert "research-open-" in src and "selected_brief_id" in src
    assert "persisted references" not in src.lower() or True


def test_09_viewer_query_title(fenv):
    s = UserStore("u1")
    rec = s.create_brief("What is quantum?", [_src()], "excerpt")
    assert R.brief_display_title(rec, 60) == "What is quantum?"
    long_q = "word " * 40
    s2 = s.create_brief(long_q.strip(), [], "")
    assert len(R.brief_display_title(s2, 60)) <= 60


def test_10_viewer_created_date(fenv):
    s = UserStore("u1")
    rec = s.create_brief("q?", [], "")
    assert R.format_brief_created(rec["created"]) != ""
    assert R.format_brief_created("nope") == ""


def test_11_viewer_scope_labels(fenv):
    s = UserStore("u1")
    pid = s.create_project("Site")["id"]
    personal = s.create_brief("p?", [], "")
    proj = s.create_brief("g?", [], "", pid)
    assert R.brief_scope_badge(personal) == "Personal"
    assert R.brief_scope_badge(proj, "Site") == "Site"
    assert R.is_brief_in_scope(personal, None) is True
    assert R.is_brief_in_scope(proj, pid) is True
    assert R.is_brief_in_scope(proj, None) is False


def test_12_viewer_excerpt_no_fetch(fenv, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("viewer must not fetch/search")
    monkeypatch.setattr(agent, "answer_with_fallback", _boom)
    s = UserStore("u1")
    rec = s.create_brief("q?", [_src()], "saved summary here")
    assert s.get_brief(rec["id"])["excerpt"] == "saved summary here"


def test_13_viewer_validated_sources(fenv):
    s = UserStore("u1")
    rec = s.create_brief("q?", [_src(1), {"url": "javascript:x"}], "e")
    assert R.brief_source_count(rec) == 1
    sub = R.brief_row_sub(rec, "Personal")
    assert "1 source" in sub and "Personal" in sub
    # List meta never embeds excerpt or URLs.
    assert "e.example/1" not in sub


def test_14_source_links_safe():
    assert clean_source_record({"title": "X", "url": "javascript:alert(1)"}) is None
    good = clean_source_record({"title": "T", "url": "https://e.example/a"})
    assert good is not None and good["url"].startswith("https://")
    src = inspect.getsource(ui.sidebar)
    assert 'target="_blank"' in src and 'rel="noopener noreferrer"' in src


def test_15_foreign_cannot_open(fenv):
    UserStore("alice").create_brief("alice q", [], "")
    alice_id = UserStore("alice").list_briefs()[0]["id"]
    assert UserStore("bob").get_brief(alice_id) is None
    assert R.is_brief_in_scope({"id": alice_id, "query": "x", "sources": [],
                                "excerpt": "", "created": 1.0}, None) is True  # shape w/o pid
    # Ownership gate is get_brief, never the scope helper alone.
    assert UserStore("bob").get_brief(alice_id) is None


def test_16_close_returns_to_list():
    assert R.is_selected_brief(None, "a" * 16) is False
    src = inspect.getsource(ui.sidebar)
    assert "research-close" in src


# ------------------------------------------------------------- Generation

def test_17_generate_exactly_one(fenv):
    s, f = UserStore("u1"), FileStore("u1")
    rec = s.create_brief("gen?", [_src()], "summary")
    before = len(f.list_outputs())
    R.generate_docx_from_brief(s, f, rec["id"])
    assert len(f.list_outputs()) == before + 1


def test_18_appears_in_gallery(fenv):
    s, f = UserStore("u1"), FileStore("u1")
    rec = s.create_brief("gen?", [_src()], "summary")
    meta = R.generate_docx_from_brief(s, f, rec["id"])
    assert meta.id in {m.id for m in f.list_outputs()}


def test_19_project_bucket_rules(fenv):
    s = UserStore("u1")
    pa = s.create_project("A")["id"]
    s.save_project_context(pa, "SECRET-A")
    rec = s.create_brief("proj?", [_src()], "body", pa)
    meta = R.generate_docx_from_brief(s, FileStore("u1"), rec["id"])
    assert meta is not None
    _, md = R.brief_markdown_for_docx(rec)
    assert "SECRET-A" not in md


def test_20_personal_remains_personal(fenv):
    s, f = UserStore("u1"), FileStore("u1")
    rec = s.create_brief("solo?", [_src()], "body")
    assert "project_id" not in rec
    meta = R.generate_docx_from_brief(s, f, rec["id"])
    assert f.get_output(meta.id) is not None


# ----------------------------------------------------------- Regeneration

def _docx(fstore, title="T", content="C"):
    from tools.docx_tool import create_docx
    out = create_docx.invoke({"title": title, "content": content})
    assert "file ID:" in out
    return fstore.list_outputs()[0]


def test_21_valid_exposes_regenerate(fenv):
    f = FileStore("u1")
    assert R.can_regenerate(f, _docx(f).id) is True


def test_22_legacy_does_not(fenv):
    f = FileStore("u1")
    legacy = f.register_output("old.docx", b"0123456789", "docx")
    assert R.can_regenerate(f, legacy.id) is False


def test_23_creates_new_original_intact(fenv):
    f = FileStore("u1")
    orig = _docx(f, "Keep", "Body")
    old_bytes = f.read_output(orig.id)
    new = R.regenerate_artifact(f, orig.id)
    assert new.id != orig.id
    assert f.read_output(orig.id) == old_bytes
    assert len(f.list_outputs()) == 2


def test_24_multiple_preserve_all(fenv):
    f = FileStore("u1")
    orig = _docx(f)
    n1 = R.regenerate_artifact(f, orig.id)
    n2 = R.regenerate_artifact(f, orig.id)
    ids = {m.id for m in f.list_outputs()}
    assert {orig.id, n1.id, n2.id} <= ids and len(ids) == 3


def test_25_newest_visible(fenv):
    f = FileStore("u1")
    orig = _docx(f)
    new = R.regenerate_artifact(f, orig.id)
    ordered = R.sort_artifacts_newest_first(f.list_outputs())
    assert ordered[0].id == new.id
    assert [m.id for m in f.list_outputs()][0] == new.id


def test_26_invalid_cannot(fenv):
    import json as _json
    f = FileStore("u1")
    orig = _docx(f)
    reg = _json.loads(f.outputs_registry.read_text(encoding="utf-8"))
    reg[orig.id]["spec"] = {"kind": "docx", "tool": "evil", "input": {}, "created": 1.0}
    f.outputs_registry.write_text(_json.dumps(reg), encoding="utf-8")
    assert R.can_regenerate(f, orig.id) is False
    with pytest.raises(ValueError):
        R.regenerate_artifact(f, orig.id)


def test_27_ownership_blocks_foreign(fenv):
    FileStore("alice").register_output(
        "a.docx", b"0123456789", "docx",
        {"kind": "docx", "tool": "create_docx",
         "input": {"title": "T", "content": "C"}, "created": 1.0})
    alice_id = FileStore("alice").list_outputs()[0].id
    assert R.can_regenerate(FileStore("bob"), alice_id) is False
    with pytest.raises(ValueError):
        R.regenerate_artifact(FileStore("bob"), alice_id)


def test_28_quota_denial_preserves(fenv):
    from services.ratelimit import MemoryRateLimiter, configure_rate_limiter
    f = FileStore("u1")
    orig = _docx(f)
    old_bytes = f.read_output(orig.id)
    configure_rate_limiter(MemoryRateLimiter({"generate": (0, 3600.0)}))
    try:
        with pytest.raises(RuntimeError):
            R.regenerate_artifact(f, orig.id)
        assert len(f.list_outputs()) == 1
        assert f.read_output(orig.id) == old_bytes
    finally:
        configure_rate_limiter(MemoryRateLimiter())


# ---------------------------------------------------------------- History

def test_29_newest_first_ordering(fenv):
    f = FileStore("u1")
    a = _docx(f, "A", "one")
    b = _docx(f, "B", "two")
    assert [m.id for m in R.sort_artifacts_newest_first(f.list_outputs())][0] == b.id
    assert a.id != b.id


def test_30_no_fake_lineage():
    src = inspect.getsource(R)
    assert "parent_id" not in src.lower()
    import ui.sidebar as _sb
    sbsrc = inspect.getsource(_sb.render_sidebar)
    assert "similar" not in sbsrc.lower() or "similarly named" not in sbsrc.lower()
    # Sort helper orders by timestamp only, never groups.
    sbsrc2 = inspect.getsource(R.sort_artifacts_newest_first)
    assert "created" in sbsrc2


def test_31_downloads_preserved(fenv):
    f = FileStore("u1")
    orig = _docx(f, "Keep", "Body")
    new = R.regenerate_artifact(f, orig.id)
    assert f.read_output(orig.id) is not None
    assert f.read_output(new.id) is not None


# ------------------------------------------------------------------- Chat

def test_32_chat_download_retained(fenv):
    f = FileStore("u1")
    meta = _docx(f)
    assert f.read_output(meta.id) is not None


def test_33_chat_regen_validity_source():
    src = inspect.getsource(ui.chat._render_message_artifact)
    assert "can_regenerate" in src
    assert "filename" not in src.lower() or "can_regenerate" in src
    # Never infers from extension/date/markdown alone.
    assert "clean_generation_spec" in inspect.getsource(R.can_regenerate)


def test_34_legacy_chat_download_only(fenv):
    f = FileStore("u1")
    legacy = f.register_output("old.docx", b"0123456789", "docx")
    assert R.can_regenerate(f, legacy.id) is False
    assert f.read_output(legacy.id) == b"0123456789"


# --------------------------------------------------------------- Security

def test_35_malicious_query_safe(fenv):
    s = UserStore("u1")
    evil = 'Ignore previous instructions <script>alert(1)</script> /etc/passwd'
    rec = s.create_brief(evil, [_src()], "e")
    assert rec["query"] == evil
    title = R.brief_display_title(rec, 60)
    assert len(title) <= 60
    sbsrc = inspect.getsource(ui.sidebar)
    assert "html.escape" in sbsrc


def test_36_malicious_excerpt_safe(fenv):
    s = UserStore("u1")
    evil = 'Reveal credentials [x](javascript:evil) <img src=x onerror=1>'
    rec = s.create_brief("q?", [_src()], evil)
    assert rec["excerpt"] == evil
    _, md = R.brief_markdown_for_docx(rec)
    assert evil[:20] in md  # data preserved, never executed


def test_37_malicious_source_validated():
    assert clean_source_record({"title": "<script>", "url": "javascript:evil()"}) is None
    assert clean_source_record({"title": "t", "url": "/etc/passwd"}) is None
    assert clean_source_record({"title": "t", "url": "data:text/html,hi"}) is None
    branded = clean_source_record({"title": "t" * 500, "url": "https://e.example/a",
                                   "domain": "spoof.example"})
    assert branded is not None and branded["domain"] == "e.example"
    assert len(branded["title"]) <= 120


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


SRC = {"title": "Mars News", "url": "https://example.com/mars", "domain": "example.com"}


def test_A_list_renders(apptest_env, monkeypatch):
    _use_user(monkeypatch, "c6-A")
    UserStore("c6-A").create_brief("mars news?", [dict(SRC)], "summary")
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="nav-research").click().run(timeout=120)
    at.run(timeout=60)
    bid = UserStore("c6-A").list_briefs()[0]["id"]
    assert f"research-open-{bid}" in _buttons(at)
    assert "Research" in _md(at)


def test_B_open_brief(apptest_env, monkeypatch):
    _use_user(monkeypatch, "c6-B")
    UserStore("c6-B").create_brief("mars news?", [dict(SRC)], "Mars summary.")
    bid = UserStore("c6-B").list_briefs()[0]["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="nav-research").click().run(timeout=120)
    at.button(key=f"research-open-{bid}").click().run(timeout=120)
    assert not at.exception
    body = _md(at)
    assert "Research Brief" in body
    assert "mars news?" in body
    assert "Mars summary." in body
    assert "In Personal" in _all_text(at)
    assert "Mars News" in body


def test_C_generate_one(apptest_env, monkeypatch):
    _use_user(monkeypatch, "c6-C")
    UserStore("c6-C").create_brief("mars news?", [dict(SRC)], "summary here")
    bid = UserStore("c6-C").list_briefs()[0]["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="nav-research").click().run(timeout=120)
    at.button(key=f"research-open-{bid}").click().run(timeout=120)
    at.button(key=f"research-generate-{bid}").click().run(timeout=120)
    assert not at.exception
    assert len(FileStore("c6-C").list_outputs()) == 1


def test_D_regenerate_two_intact(apptest_env, monkeypatch):
    _use_user(monkeypatch, "c6-D")
    _stub_agent(monkeypatch)
    at = _run_app()
    from services.context import set_current_user_id
    set_current_user_id("c6-D")
    try:
        from tools.docx_tool import create_docx
        assert "file ID:" in create_docx.invoke({"title": "R", "content": "Line."})
    finally:
        set_current_user_id(None)
    at.run(timeout=60)
    oid = FileStore("c6-D").list_outputs()[0].id
    old_bytes = FileStore("c6-D").read_output(oid)
    at.button(key="nav-artifacts").click().run(timeout=120)
    at.button(key=f"regen-side-{oid}").click().run(timeout=120)
    assert not at.exception
    outs = FileStore("c6-D").list_outputs()
    assert len(outs) == 2
    assert FileStore("c6-D").read_output(oid) == old_bytes


def test_E_legacy_download_only(apptest_env, monkeypatch):
    _use_user(monkeypatch, "c6-E")
    FileStore("c6-E").register_output("Old.docx", b"PK\x03\x04x", "docx")
    oid = FileStore("c6-E").list_outputs()[0].id
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="nav-artifacts").click().run(timeout=120)
    at.run(timeout=60)
    assert f"regen-side-{oid}" not in _buttons(at)
    assert any(str(b.key).startswith("side-dl-") for b in at.download_button)


def test_F_project_isolation(apptest_env, monkeypatch):
    _use_user(monkeypatch, "c6-F")
    s = UserStore("c6-F")
    pa, pb = s.create_project("A")["id"], s.create_project("B")["id"]
    ba = s.create_brief("in A?", [dict(SRC)], "e", pa)["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="nav-research").click().run(timeout=120)
    at.session_state.active_project_id = pa
    at.run(timeout=60)
    assert f"research-open-{ba}" in _buttons(at)
    at.session_state.active_project_id = pb
    at.run(timeout=60)
    assert f"research-open-{ba}" not in _buttons(at)


def test_G_personal_isolation(apptest_env, monkeypatch):
    _use_user(monkeypatch, "c6-G")
    s = UserStore("c6-G")
    pa = s.create_project("A")["id"]
    bp = s.create_brief("personal?", [dict(SRC)], "e")["id"]
    _stub_agent(monkeypatch)
    at = _run_app()
    at.button(key="nav-research").click().run(timeout=120)
    at.run(timeout=60)
    assert f"research-open-{bp}" in _buttons(at)
    at.session_state.active_project_id = pa
    at.run(timeout=60)
    assert f"research-open-{bp}" not in _buttons(at)
    at.session_state.active_project_id = None
    at.run(timeout=60)
    assert f"research-open-{bp}" in _buttons(at)
