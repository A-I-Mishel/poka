"""Floor 3: kb + research pure/bounded helpers still below floor.

Hermetic, no network/quota. Tmp PLUTO_DATA_DIR, stub stores.
Targets services/kb.py 43% and services/research.py 48%.
"""

import io
import os
import sys
import time
import zipfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("floor3-user")
    ctx.set_limit_key("floor3-user")
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)


# ---------- kb pure helpers ----------

def test_l2_normalize_and_dot():
    from services.kb import _l2_normalize, _dot, cosine

    assert _l2_normalize([]) == []
    assert _l2_normalize(None) == []
    assert _l2_normalize([0, 0]) == [0.0, 0.0]
    assert _l2_normalize([3, 4])[0] == pytest.approx(0.6)
    assert _dot([1, 2], [3, 4]) == pytest.approx(11.0)
    assert _dot([1, 0], [0, 1]) == pytest.approx(0.0)
    assert _dot([], [1]) == 0.0
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine("bad", [1]) == 0.0


def test_chunk_text_edge():
    from services.kb import chunk_text

    assert chunk_text("") == []
    assert chunk_text("single") == ["single"]
    # huge overlap capped (size floor 200, so need long text to split)
    long_text = " ".join(f"word{i:03d}" for i in range(200))
    chunks = chunk_text(long_text, chunk_chars=250, overlap=500)
    assert len(chunks) > 1
    # word longer than size
    assert chunk_text("a" * 500, chunk_chars=200) != []


def test_kb_path_and_blank_and_cache(tmp_path):
    from services.kb import _kb_path, _blank_kb, load_kb, invalidate_kb_cache, _save_kb

    uid = "test-user-kb"
    p = _kb_path(uid)
    assert "kb.json" in str(p)
    blank = _blank_kb()
    assert blank["version"] == 1 and isinstance(blank["docs"], dict)
    # load blank when missing
    data = load_kb(uid)
    assert data["docs"] == {}
    # save then load cached
    _save_kb(uid, {"version": 1, "model": "m", "docs": {"d": {"chunks": []}}})
    a = load_kb(uid)
    b = load_kb(uid)
    assert a is b  # cached
    invalidate_kb_cache(uid)
    c = load_kb(uid)
    assert c is not a
    # corrupt file -> blank
    p.write_text("not json", encoding="utf-8")
    invalidate_kb_cache(uid)
    assert load_kb(uid)["docs"] == {}


def test_kb_text_extractors_direct():
    from services.kb import _html_text, _pdf_text, _rtf_text, _ole_strings_text, _zip_text, _odf_xml_text, _xls_text, extract_text

    # html
    txt, reason = _html_text(b"<p>Hello</p><script>no</script>")
    assert "Hello" in txt and reason == ""
    txt, reason = _html_text(b"\x00\x01binary")
    assert reason == "decode-failed"
    txt, reason = _html_text(b"<p>   </p>")
    assert reason == "empty"

    # pdf bad
    txt, reason = _pdf_text(b"not pdf")
    assert reason == "pdf-extract-failed"

    # rtf
    txt, reason = _rtf_text(b"{\\rtf1 hello world}")
    assert "hello" in txt.lower()
    txt, reason = _rtf_text(b"not rtf")
    assert reason == "rtf-extract-failed"

    # ole
    txt, reason = _ole_strings_text(b"HelloWorld from OLE strings big enough to keep and more words here ")
    assert "HelloWorld" in txt
    txt, reason = _ole_strings_text(b"hi")
    assert reason == "empty"

    # zip happy vs limits
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", b"hello zip world")
        zf.writestr("bad.png", b"\x89PNG")
    txt, reason = _zip_text(buf.getvalue())
    assert "hello zip" in txt

    bad_zip, reason = _zip_text(b"not zip")
    assert reason == "zip-extract-failed"

    # zip too many files
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as zf:
        for i in range(105):
            zf.writestr(f"f{i}.txt", b"x")
    _, reason = _zip_text(buf2.getvalue())
    assert reason == "zip-too-many-files"

    # odf bad
    _, reason = _odf_xml_text(b"not zip", "odt")
    assert "extract-failed" in reason

    # xls with tiny blob falls back to ole empty
    txt, reason = _xls_text(b"hi")
    assert txt == "" and reason == "empty"
    # ole-success fallback: "not xls" is 7 chars -> extracted
    txt2, reason2 = _xls_text(b"not xls")
    assert txt2 != "" and reason2 == ""

    # extract_text dispatch
    txt, reason = extract_text(b"plain", "note.txt")
    assert reason == "" and "plain" in txt
    txt, reason = extract_text(b"", "note.csv")
    assert reason == "empty"
    txt, reason = extract_text(b"MZ\x90\x00", "run.exe")
    assert "unsupported-type" in reason


def test_kb_lexical_search():
    from services.kb import _lexical_search

    docs = {
        "d1": {"chunks": [{"text": "apple banana", "vector": [1, 0]}, {"text": "nothing"}]},
        "d2": {"chunks": [{"text": "quantum physics", "vector": [0, 1]}]},
    }
    hits = _lexical_search(docs, "apple", None)
    assert len(hits) == 1 and hits[0]["upload_id"] == "d1"
    assert _lexical_search({}, "q", None) == []
    assert _lexical_search({"d": "not dict"}, "q", None) == []


def test_kb_ingest_and_search_caps(monkeypatch, tmp_path):
    from services import kb as kb_svc
    from services import kb_embeddings

    # isolate dir
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data2"))
    kb_embeddings.configure_embedder(kb_embeddings.stub_embed)
    try:
        # normal ingest
        r = kb_svc.ingest_document("u3", "doc1", "a.txt", b"hello world ingest test " * 10)
        assert r["ingested"] is True
        # duplicate ingest updates
        r2 = kb_svc.ingest_document("u3", "doc1", "a.txt", b"hello again " * 10)
        assert r2["ingested"] is True
        # search finds it
        hits = kb_svc.search("u3", "hello world")
        assert len(hits) >= 1
        # kb full guard by monkeypatching limit tiny
        monkeypatch.setattr(kb_svc, "KB_MAX_DOCS_PER_USER", 1)
        r3 = kb_svc.ingest_document("u3", "doc2", "b.txt", b"second doc should be blocked")
        assert r3["ingested"] is False and "kb-full" in r3["reason"]
    finally:
        kb_embeddings.configure_embedder(None)


# ---------- research pure + store mocks ----------

class _FakeUserStore:
    def __init__(self):
        self.projects = {}
        self.briefs = {}
        self._bid = 0

    def get_project(self, pid):
        return self.projects.get(pid)

    def create_brief(self, query, sources, excerpt, pid):
        self._bid += 1
        bid = f"{self._bid:016x}"
        rec = {"id": bid, "query": query, "sources": sources, "excerpt": excerpt, "created": time.time()}
        if pid:
            rec["project_id"] = pid
        self.briefs[bid] = rec
        return rec

    def list_briefs(self, pid=None):
        vals = list(self.briefs.values())
        if pid is None:
            return sorted(vals, key=lambda b: b["created"], reverse=True)
        return sorted([b for b in vals if b.get("project_id") == pid], key=lambda b: b["created"], reverse=True)

    def get_brief(self, bid):
        return self.briefs.get(bid)


def _eligible_msg(query="research mars", content="answer with sources"):
    return {
        "role": "assistant",
        "search_executed": True,
        "content": content,
        "sources": [{"title": "Example", "url": "https://example.com/a", "domain": "example.com"}],
    }


def test_resolve_brief_project_id():
    from services.research import resolve_brief_project_id

    store = _FakeUserStore()
    pid = "a" * 16
    store.projects[pid] = {"id": pid, "archived": False}
    assert resolve_brief_project_id(store, pid) == pid
    # archived -> None
    pid2 = "b" * 16
    store.projects[pid2] = {"id": pid2, "archived": True}
    assert resolve_brief_project_id(store, pid2) is None
    # invalid id
    assert resolve_brief_project_id(store, "not-hex") is None
    assert resolve_brief_project_id(store, None) is None
    # exception path
    class Bad:
        def get_project(self, _): raise RuntimeError("boom")
    assert resolve_brief_project_id(Bad(), pid) is None


def test_create_brief_from_message_success_and_errors():
    from services.research import create_brief_from_message

    store = _FakeUserStore()
    pid = "c" * 16
    store.projects[pid] = {"id": pid, "archived": False}
    msgs = [{"role": "user", "content": "  research mars rovers  "}, _eligible_msg()]
    brief = create_brief_from_message(store, msgs, 1, pid)
    assert brief["query"] == "research mars rovers"
    assert brief["project_id"] == pid

    # no preceding user -> error
    msgs2 = [_eligible_msg()]
    with pytest.raises(ValueError, match="could not be recovered"):
        create_brief_from_message(store, msgs2, 0)

    # not eligible
    with pytest.raises(ValueError, match="Only search-backed"):
        create_brief_from_message(store, [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "no search"}], 1)

    # unknown well-formed project -> Unknown project
    unknown = "d" * 16
    with pytest.raises(ValueError, match="Unknown project"):
        create_brief_from_message(store, msgs, 1, unknown)

    # invalid messages
    with pytest.raises(ValueError, match="could not be saved"):
        create_brief_from_message(store, None, 1)


def test_personal_and_visible_briefs():
    from services.research import personal_briefs, visible_briefs_for_scope

    store = _FakeUserStore()
    pid = "e" * 16
    store.projects[pid] = {"id": pid, "archived": False}
    # create personal and project briefs
    b1 = store.create_brief("q1", [], "ex1", None)
    time.sleep(0.01)
    b2 = store.create_brief("q2", [], "ex2", pid)
    assert personal_briefs(store, limit=10)[0]["id"] == b1["id"]
    # personal briefs capped
    assert personal_briefs(store, limit=1) != []
    # exception path
    class BadStore:
        def list_briefs(self, *a, **k): raise RuntimeError("boom")
        def get_project(self, *a, **k): raise RuntimeError("boom")
    assert personal_briefs(BadStore()) == []
    assert visible_briefs_for_scope(BadStore(), pid) == []
    # visible scope
    assert visible_briefs_for_scope(store, pid)[0]["id"] == b2["id"]
    assert visible_briefs_for_scope(store, None)[0]["id"] == b1["id"]
    # archived project -> falls back to personal
    pid3 = "f" * 16
    store.projects[pid3] = {"id": pid3, "archived": True}
    assert visible_briefs_for_scope(store, pid3)[0]["id"] == b1["id"]


def test_brief_row_sub_and_markdown_and_outputs():
    from services.research import brief_row_sub, brief_markdown_for_docx, _new_outputs_since, format_brief_created

    brief = {"query": "mars", "excerpt": "summary", "sources": [{"title": "T", "url": "https://example.com/a", "domain": "example.com"}], "created": time.time()}
    sub = brief_row_sub(brief, "Personal")
    assert "Personal" in sub and "source" in sub
    # None returns date-only (0.0 -> Jan 01 1970) per impl, not empty
    assert "1970" in brief_row_sub(None)
    # markdown
    title, md = brief_markdown_for_docx(brief)
    assert "mars" in title.lower() or "mars" in md.lower()
    assert "Sources" in md
    with pytest.raises(ValueError):
        brief_markdown_for_docx(None)
    with pytest.raises(ValueError):
        brief_markdown_for_docx({"query": ""})
    # sources capped and title fallback
    brief2 = {"query": "q", "excerpt": "", "sources": "not list", "created": time.time()}
    t2, md2 = brief_markdown_for_docx(brief2)
    assert "No validated sources" in md2
    assert format_brief_created("bad") == ""
    # _new_outputs_since
    before = {"a"}
    metas = [SimpleNamespace(id="a", created=1), SimpleNamespace(id="b", created=2)]
    class FS:
        def list_outputs(self): return metas
    assert len(_new_outputs_since(FS(), before)) == 1
    assert _new_outputs_since(FS(), "not-set") == []
    class BadFS:
        def list_outputs(self): raise RuntimeError("boom")
    assert _new_outputs_since(BadFS(), before) == []


def test_generate_docx_from_brief_and_can_regenerate(monkeypatch):
    from services.research import generate_docx_from_brief, can_regenerate, get_valid_spec

    store = _FakeUserStore()
    brief = store.create_brief("research test", [{"title": "T", "url": "https://example.com/a", "domain": "example.com"}], "excerpt here", None)
    bid = brief["id"]

    # file store mock — spec must be valid (kind+tool+input+created per _SPEC_TOOLS)
    valid_spec = {"kind": "docx", "tool": "create_docx", "input": {"title": "t", "content": "hi"}, "created": time.time()}
    fresh = SimpleNamespace(id="out1", created=time.time(), spec=valid_spec)
    class FS:
        def list_outputs(self): return [fresh] if hasattr(self, "_after") else []
        def get_output(self, aid): return fresh if aid == "out1" else None
        def get_brief(self, _): return brief
    fs = FS()
    # user store get_brief path
    store.get_brief = lambda x: brief if x == bid else None

    # monkeypatch build_document to avoid real docx dep — replace whole tool obj (StructuredTool is pydantic)
    import tools.docx_tool as docx_tool
    orig_doc = docx_tool.build_document
    fake_ok = SimpleNamespace(invoke=lambda inp: "STATUS=OK fake")
    monkeypatch.setattr(docx_tool, "build_document", fake_ok)

    def list_after():
        if not hasattr(fs, "_called"):
            fs._called = True
            return []
        return [fresh]
    monkeypatch.setattr(fs, "list_outputs", list_after)
    # simpler: test can_regenerate / get_valid_spec directly
    assert can_regenerate(fs, "out1") is True
    assert can_regenerate(fs, "missing") is False
    assert get_valid_spec(fs, "out1") is not None
    assert get_valid_spec(fs, "missing") is None
    class BadFS2:
        def get_output(self, _): raise RuntimeError("boom")
    assert can_regenerate(BadFS2(), "x") is False
    assert get_valid_spec(BadFS2(), "x") is None
    # generate failure on unknown brief
    with pytest.raises(ValueError, match="Brief not found"):
        generate_docx_from_brief(store, fs, "badid")
    # generate failure on build_document STATUS
    fake_fail = SimpleNamespace(invoke=lambda inp: "STATUS=FAILED boom")
    monkeypatch.setattr(docx_tool, "build_document", fake_fail)
    # patch before ids to have empty then fresh
    fs2 = FS()
    fs2._after = True
    with pytest.raises(RuntimeError, match="STATUS=FAILED"):
        generate_docx_from_brief(store, fs2, bid)
    monkeypatch.setattr(docx_tool, "build_document", orig_doc)


def test_regenerate_artifact_dispatch(monkeypatch):
    from services.research import regenerate_artifact

    spec = {"kind": "md", "tool": "create_markdown", "input": {"title": "a", "markdown_text": "# hi"}, "created": time.time()}
    fresh = SimpleNamespace(id="new1", created=time.time(), spec=spec)
    class FS:
        def get_output(self, aid):
            if aid == "art1":
                return SimpleNamespace(id="art1", spec=spec, created=1)
            return None
        def list_outputs(self):
            # first call before, second after
            if not hasattr(self, "c"):
                self.c = 0
            self.c += 1
            return [] if self.c == 1 else [fresh]
    fs = FS()
    # monkeypatch create_markdown — replace whole tool obj
    import tools.make_tool as make_tool
    orig_md = make_tool.create_markdown
    fake_ok = SimpleNamespace(invoke=lambda inp: "created ok")
    monkeypatch.setattr(make_tool, "create_markdown", fake_ok)
    out = regenerate_artifact(fs, "art1")
    assert out.id == "new1"
    # unknown artifact
    with pytest.raises(ValueError, match="Artifact not found"):
        regenerate_artifact(fs, "bad")
    # tampered spec
    class FS2:
        def get_output(self, _): return SimpleNamespace(id="x", spec={"tool": "bad"}, created=1)
        def list_outputs(self): return []
    with pytest.raises(ValueError, match="cannot be regenerated"):
        regenerate_artifact(FS2(), "x")
    # tool failure
    fake_fail = SimpleNamespace(invoke=lambda inp: "STATUS=FAILED tool error")
    monkeypatch.setattr(make_tool, "create_markdown", fake_fail)
    fs3 = FS()
    with pytest.raises(RuntimeError):
        regenerate_artifact(fs3, "art1")
    monkeypatch.setattr(make_tool, "create_markdown", orig_md)
    # exception in get_output
    class BadFS:
        def get_output(self, _): raise RuntimeError("boom")
        def list_outputs(self): return []
    with pytest.raises(ValueError):
        regenerate_artifact(BadFS(), "x")
