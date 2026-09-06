"""Phase 6A foundation tests: briefs registry + artifact spec capture.

Hermetic: tmp POKA_DATA_DIR, direct stores, real generation tools with
a request-scoped user (no LLM calls). No UI, no network.
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services.files import FileStore
from services.limits import (
    MAX_BRIEF_EXCERPT_CHARS,
    MAX_BRIEF_QUERY_CHARS,
)
from services.storage import (
    MAX_SOURCES,
    UserStore,
    clean_generation_spec,
    is_valid_id,
)


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def fenv(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    ctx.set_current_user_id("f-user")
    yield tmp_path / "data"
    ctx.set_current_user_id(None)


def _src(i=1):
    return {"title": f"T{i}", "url": f"https://e.example/{i}",
            "domain": "e.example"}


# -- briefs: create/read -------------------------------------------------

def test_brief_create(fenv):
    store = UserStore("f-user")
    record = store.create_brief("What is X?", [_src()], "excerpt here")
    assert is_valid_id(record["id"])
    assert record["query"] == "What is X?"
    assert record["sources"] == [_src()]
    assert record["excerpt"] == "excerpt here"
    assert isinstance(record["created"], float)
    assert "project_id" not in record  # absent, never null


def test_brief_id_generation(fenv):
    store = UserStore("f-user")
    ids = {store.create_brief(f"q{i}", [], "")["id"] for i in range(10)}
    assert len(ids) == 10 and all(is_valid_id(i) for i in ids)


def test_brief_validation(fenv):
    store = UserStore("f-user")
    for bad_query in ["", "   ", None, 123]:
        with pytest.raises(ValueError):
            store.create_brief(bad_query, [], "")
    with pytest.raises(ValueError):
        store.create_brief("q", [], 123)
    with pytest.raises(ValueError):
        store.create_brief("q", "not-a-list", "")
    with pytest.raises(ValueError):
        store.create_brief("q", [], "", project_id="nope")
    with pytest.raises(ValueError):
        store.create_brief("q", [], "", project_id="a" * 16)
    assert store.list_briefs() == []


def test_brief_source_validation(fenv):
    store = UserStore("f-user")
    record = store.create_brief("q", [
        _src(),
        {"title": "Bad", "url": "javascript:evil()"},
        "junk",
        {"title": "NoUrl"},
    ], "")
    assert record["sources"] == [_src()]


def test_brief_source_cap(fenv):
    store = UserStore("f-user")
    sources = [{"title": f"T{i}", "url": f"https://e.example/{i}",
                "domain": "e.example"} for i in range(1, 12)]
    record = store.create_brief("q", sources, "")
    assert len(record["sources"]) == MAX_SOURCES == 6
    assert record["sources"][0]["url"] == "https://e.example/1"


def test_brief_query_cap(fenv):
    store = UserStore("f-user")
    store.create_brief("q" * MAX_BRIEF_QUERY_CHARS, [], "")
    with pytest.raises(ValueError):
        store.create_brief("q" * (MAX_BRIEF_QUERY_CHARS + 1), [], "")
    assert len(store.list_briefs()) == 1


def test_brief_excerpt_cap(fenv):
    store = UserStore("f-user")
    store.create_brief("q", [], "e" * MAX_BRIEF_EXCERPT_CHARS)
    with pytest.raises(ValueError):
        store.create_brief("q", [], "e" * (MAX_BRIEF_EXCERPT_CHARS + 1))
    assert store.list_briefs()[0]["excerpt"] == "e" * MAX_BRIEF_EXCERPT_CHARS


def test_brief_round_trip(fenv):
    store = UserStore("f-user")
    pid = store.create_project("Site")["id"]
    created = store.create_brief("Deep question?", [_src(1), _src(2)],
                                 "Longer excerpt here.", pid)
    assert created["project_id"] == pid
    fetched = store.get_brief(created["id"])
    assert fetched == created
    assert fetched is not created  # safe copy


def test_brief_list_newest_first(fenv):
    store = UserStore("f-user")
    first = store.create_brief("first", [], "")
    reg = json.loads(store._briefs_path().read_text(encoding="utf-8"))
    for entry in reg["briefs"]:
        if entry["id"] == first["id"]:
            entry["created"] -= 100
    store._briefs_path().write_text(json.dumps(reg), encoding="utf-8")
    second = store.create_brief("second", [], "")
    assert [b["id"] for b in store.list_briefs()] == [second["id"], first["id"]]


def test_brief_project_filter(fenv):
    store = UserStore("f-user")
    pid = store.create_project("Site")["id"]
    other = store.create_project("Other")["id"]
    mine = store.create_brief("in project", [], "", pid)["id"]
    personal = store.create_brief("personal", [], "")["id"]
    assert [b["id"] for b in store.list_briefs(pid)] == [mine]
    assert [b["id"] for b in store.list_briefs(other)] == []
    assert {b["id"] for b in store.list_briefs()} == {mine, personal}
    assert "project_id" not in store.get_brief(personal)


def test_brief_personal_behavior(fenv):
    store = UserStore("f-user")
    record = store.create_brief("solo", [], "")
    assert "project_id" not in record
    assert store.list_briefs("f" * 16) == []  # unknown project: empty, no crash


def test_brief_delete(fenv):
    store = UserStore("f-user")
    doomed = store.create_brief("gone", [], "")["id"]
    kept = store.create_brief("kept", [], "")["id"]
    assert store.delete_brief(doomed) is True
    assert store.get_brief(doomed) is None
    assert [b["id"] for b in store.list_briefs()] == [kept]
    assert store.delete_brief(doomed) is False
    assert store.delete_brief("nope") is False


# -- briefs: malformed / isolation / atomicity ------------------------------

def test_brief_malformed_registry(fenv):
    store = UserStore("f-user")
    store._briefs_path().parent.mkdir(parents=True, exist_ok=True)
    store._briefs_path().write_text("{not valid json", encoding="utf-8")
    data, warnings = store.load_briefs()
    assert data == {"version": 1, "briefs": []}
    assert warnings != []
    assert list(store._briefs_path().parent.glob("briefs.corrupt-*")) != []
    store._briefs_path().write_text("[1, 2]", encoding="utf-8")
    data, _ = store.load_briefs()
    assert data["briefs"] == []


def test_brief_malformed_records_skipped(fenv):
    store = UserStore("f-user")
    good = {"id": "a" * 16, "query": "ok?", "sources": [], "excerpt": "",
            "created": 1700000000.0}
    store.save_briefs([
        good,
        {"no": "id"},
        {"id": "bad!!", "query": "x", "sources": [], "excerpt": ""},
        {"id": "b" * 16, "query": "   ", "sources": [], "excerpt": ""},
        {"id": "c" * 16, "query": "x" * 600, "sources": [], "excerpt": ""},
        {"id": "d" * 16, "query": "y", "sources": "nope", "excerpt": ""},
        "junk",
    ])
    data, _ = store.load_briefs()
    assert [b["id"] for b in data["briefs"]] == ["a" * 16, "c" * 16, "d" * 16]
    assert data["briefs"][1]["query"] == "x" * 500


def test_brief_duplicate_ids(fenv):
    store = UserStore("f-user")
    dup = {"id": "a" * 16, "query": "first", "sources": [], "excerpt": "",
           "created": 1.0}
    store.save_briefs([dup, dict(dup, query="second")])
    assert store.get_brief("a" * 16)["query"] == "first"


def test_brief_foreign_id(fenv):
    UserStore("f-alice").create_brief("alice q", [], "")
    alice_id = UserStore("f-alice").list_briefs()[0]["id"]
    bob = UserStore("f-bob")
    assert bob.get_brief(alice_id) is None
    assert bob.list_briefs() == []
    assert bob.delete_brief(alice_id) is False
    assert UserStore("f-alice").get_brief(alice_id) is not None


def test_brief_isolation(fenv):
    UserStore("f-alice").create_brief("a?", [], "")
    assert UserStore("f-bob").list_briefs() == []
    UserStore("f-bob").create_brief("b?", [], "")
    assert len(UserStore("f-alice").list_briefs()) == 1
    assert len(UserStore("f-bob").list_briefs()) == 1


def test_brief_atomic_failure_preserves(fenv, monkeypatch):
    import services.storage as storage_mod
    from services.storage import StorageError

    store = UserStore("f-user")
    store.create_brief("keep me", [], "")
    before = store._briefs_path().read_text(encoding="utf-8")

    def _boom(path, payload):
        raise StorageError("disk gone")

    monkeypatch.setattr(storage_mod, "_write_json", _boom)
    with pytest.raises(StorageError):
        store.create_brief("lost", [], "")
    assert store._briefs_path().read_text(encoding="utf-8") == before


def test_brief_legacy_no_file(fenv):
    store = UserStore("fresh-user")
    data, warnings = store.load_briefs()
    assert data == {"version": 1, "briefs": []}
    assert warnings == []
    assert not os.path.exists(store._briefs_path())  # load creates nothing


# -- artifact specs: cleaner ----------------------------------------------------

def test_spec_cleaner_valid():
    from services.storage import clean_generation_spec

    good = {"kind": "docx", "tool": "build_document",
            "input": {"title": "T", "markdown_text": "# Hi"},
            "created": 1700000000.0}
    assert clean_generation_spec(good) == good
    assert clean_generation_spec(
        {"kind": "pptx", "tool": "create_pptx",
         "input": {"topic": "T", "content": "C"}, "created": 1})["created"] == 1.0


def test_spec_cleaner_rejects():
    from services.storage import clean_generation_spec

    base = {"kind": "docx", "tool": "build_document",
            "input": {"title": "T", "markdown_text": "M"}, "created": 1.0}
    cases = [
        None, "x", 123, [],
        dict(base, kind="xlsx"),
        dict(base, tool="nope"),
        dict(base, tool="create_pptx"),  # kind/tool mismatch
        dict(base, input={"title": "T"}),  # missing key
        dict(base, input={"title": "T", "markdown_text": "M", "extra": 1}),
        dict(base, input={"title": "", "markdown_text": "M"}),
        dict(base, input={"title": 5, "markdown_text": "M"}),
        dict(base, input=["not", "a", "dict"]),
        dict(base, created="yesterday"),
        dict(base, created=True),
        dict(base, created=-5),
        {k: v for k, v in base.items() if k != "created"},
    ]
    for bad in cases:
        assert clean_generation_spec(bad) is None, bad
    huge = dict(base, input={"title": "T", "markdown_text": "M" * 100_001})
    assert clean_generation_spec(huge) is None


# -- artifact specs: capture at generation paths ----------------------------------

def _gen_setup(monkeypatch, user):
    from services import context as ctx

    ctx.set_current_user_id(user)
    return user


def _gen_teardown():
    from services import context as ctx

    ctx.set_current_user_id(None)


def test_spec_captured_create_docx(fenv, monkeypatch):
    from tools.docx_tool import create_docx

    _gen_setup(monkeypatch, "g-user")
    try:
        out = create_docx.invoke({"title": "My Title",
                                  "content": "First line.\nSecond line."})
        assert "file ID:" in out
        metas = FileStore("g-user").list_outputs()
        assert len(metas) == 1
        assert metas[0].spec == {
            "kind": "docx", "tool": "create_docx",
            "input": {"title": "My Title",
                      "content": "First line.\nSecond line."},
            "created": metas[0].spec["created"],
        }
    finally:
        _gen_teardown()


def test_spec_captured_build_document(fenv, monkeypatch):
    from tools.docx_tool import build_document

    _gen_setup(monkeypatch, "g-user")
    try:
        out = build_document.invoke({"markdown_text": "# Report\n\nSome analysis here.",
                                     "title": "Report"})
        assert "file ID:" in out
        spec = FileStore("g-user").list_outputs()[0].spec
        assert spec["tool"] == "build_document"
        assert spec["input"]["markdown_text"] == "# Report\n\nSome analysis here."
        assert spec["input"]["title"] == "Report"
    finally:
        _gen_teardown()


def test_spec_captured_create_pptx(fenv, monkeypatch):
    from tools.pptx_tool import create_pptx

    _gen_setup(monkeypatch, "g-user")
    try:
        out = create_pptx.invoke({"topic": "Deck",
                                  "content": "Slide one\n- point a\n- point b"})
        assert "file ID:" in out
        spec = FileStore("g-user").list_outputs()[0].spec
        assert spec["tool"] == "create_pptx"
        assert spec["input"]["topic"] == "Deck"
    finally:
        _gen_teardown()


def test_spec_captured_build_presentation(fenv, monkeypatch):
    import json as json_mod

    from tools.pptx_tool import build_presentation

    _gen_setup(monkeypatch, "g-user")
    spec_json = json_mod.dumps({
        "title": "Deck",
        "slides": [{"type": "bullets", "title": "Intro",
                    "bullets": ["one", "two"]}],
    })
    try:
        out = build_presentation.invoke({"spec_json": spec_json})
        assert "file ID:" in out, out
        spec = FileStore("g-user").list_outputs()[0].spec
        assert spec == {"kind": "pptx", "tool": "build_presentation",
                        "input": {"spec_json": spec_json},
                        "created": spec["created"]}
    finally:
        _gen_teardown()


def test_spec_round_trip(fenv):
    store = FileStore("f-user")
    meta = store.register_output(
        "d.docx", b"0123456789", "docx",
        {"kind": "docx", "tool": "create_docx",
         "input": {"title": "T", "content": "C"}, "created": 1700000000.0})
    assert meta.spec is not None and meta.spec["tool"] == "create_docx"
    again = store.get_output(meta.id)
    assert again is not None and again.spec == meta.spec
    assert store.list_outputs()[0].spec == meta.spec


def test_spec_invalid_dropped_silently(fenv):
    store = FileStore("f-user")
    meta = store.register_output("d.docx", b"0123456789", "docx",
                                 {"kind": "docx", "tool": "nope"})
    assert meta.spec is None
    assert store.get_output(meta.id).spec is None


def test_legacy_artifact_without_spec(fenv):
    store = FileStore("f-user")
    meta = store.register_output("old.docx", b"0123456789", "docx")
    assert meta.spec is None
    record = json.loads(store.outputs_registry.read_text(encoding="utf-8"))
    assert "spec" not in record[meta.id] or record[meta.id]["spec"] is None
    assert store.get_output(meta.id) is not None
    assert store.read_output(meta.id) == b"0123456789"


def test_legacy_record_missing_spec_key(fenv):
    store = FileStore("f-user")
    meta = store.register_output("old.docx", b"0123456789", "docx")
    reg = json.loads(store.outputs_registry.read_text(encoding="utf-8"))
    del reg[meta.id]["spec"]
    store.outputs_registry.write_text(json.dumps(reg), encoding="utf-8")
    fetched = store.get_output(meta.id)
    assert fetched is not None and fetched.spec is None
    assert fetched.display_name == "old.docx"


def test_spec_tampered_dropped(fenv):
    store = FileStore("f-user")
    meta = store.register_output(
        "d.docx", b"0123456789", "docx",
        {"kind": "docx", "tool": "create_docx",
         "input": {"title": "T", "content": "C"}, "created": 1.0})
    reg = json.loads(store.outputs_registry.read_text(encoding="utf-8"))
    reg[meta.id]["spec"] = {"kind": "docx", "tool": "evil_tool",
                            "input": {"x": "y"}, "created": 1.0}
    store.outputs_registry.write_text(json.dumps(reg), encoding="utf-8")
    assert store.get_output(meta.id).spec is None


def test_spec_cross_user_isolated(fenv):
    FileStore("f-alice").register_output(
        "a.docx", b"0123456789", "docx",
        {"kind": "docx", "tool": "create_docx",
         "input": {"title": "T", "content": "C"}, "created": 1.0})
    alice_id = FileStore("f-alice").list_outputs()[0].id
    assert FileStore("f-bob").get_output(alice_id) is None
    assert FileStore("f-bob").read_output(alice_id) is None


def test_download_bytes_unchanged_with_spec(fenv):
    store = FileStore("f-user")
    meta = store.register_output(
        "d.docx", b"0123456789", "docx",
        {"kind": "docx", "tool": "create_docx",
         "input": {"title": "T", "content": "C"}, "created": 1.0})
    assert store.read_output(meta.id) == b"0123456789"


def test_failed_generation_registers_nothing(fenv, monkeypatch):
    from services import context as ctx
    from tools.docx_tool import build_document

    ctx.set_current_user_id("g-user")
    try:
        out = build_document.invoke({"markdown_text": "   ", "title": "Empty"})
        assert out.startswith("STATUS=INVALID")
        assert FileStore("g-user").list_outputs() == []
    finally:
        ctx.set_current_user_id(None)
