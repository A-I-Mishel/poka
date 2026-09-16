"""Coverage floor: document/CSV/research paths below the 60% gate.

Hermetic: tmp PLUTO_DATA_DIR, direct stores, in-memory files.
No network, no credentials, no quota.
"""

import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services.files import FileStore
from services.limits import RESEARCH_MAX_SOURCES


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "floor-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("floor-user")
    ctx.set_limit_key("floor-user")
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)


# ---------------------------------------------------------------- CSV tools

CSV_BASIC = b"a,b\n1,2\n3,4\n"


def _upload_csv(payload: bytes = CSV_BASIC, name: str = "d.csv"):
    return FileStore("floor-user").save_upload(payload, name)


def test_analyze_csv_happy_path():
    from tools.data_tool import analyze_csv

    meta = _upload_csv()
    out = analyze_csv.invoke({"upload_id": meta.id})
    assert "Rows analyzed: 2" in out
    assert "a, b" in out


def test_analyze_csv_unknown_id_denied():
    from tools.data_tool import analyze_csv

    out = analyze_csv.invoke({"upload_id": "0" * 16})
    assert out.startswith("STATUS=DENIED")


def test_analyze_csv_no_user_invalid():
    from tools.data_tool import analyze_csv

    ctx.set_current_user_id(None)
    try:
        out = analyze_csv.invoke({"upload_id": "0" * 16})
    finally:
        ctx.set_current_user_id("floor-user")
    assert out.startswith("STATUS=DENIED")


def test_csv_inspect_ops():
    from tools.data_tool import csv_inspect

    meta = _upload_csv(b"name,score\namy,9\nbo,7\ncy,8\n")
    assert "Shape: 3 rows" in csv_inspect.invoke(
        {"upload_id": meta.id, "operation": "overview"})
    assert "Mean" not in csv_inspect.invoke(
        {"upload_id": meta.id, "operation": "describe"})
    missing = csv_inspect.invoke({"upload_id": meta.id, "operation": "missing"})
    assert "Missing values" in missing
    unique = csv_inspect.invoke(
        {"upload_id": meta.id, "operation": "unique", "column": "name"})
    assert "Distinct values" in unique
    grouped = csv_inspect.invoke(
        {"upload_id": meta.id, "operation": "groupby", "params": "name,score"})
    assert "Mean of 'score'" in grouped
    head = csv_inspect.invoke(
        {"upload_id": meta.id, "operation": "head", "params": "2"})
    assert "First 2 rows" in head


def test_csv_inspect_rejects_bad_op_and_column():
    from tools.data_tool import csv_inspect

    meta = _upload_csv()
    bad = csv_inspect.invoke({"upload_id": meta.id, "operation": "pivot"})
    assert bad.startswith("STATUS=INVALID")
    unknown = csv_inspect.invoke(
        {"upload_id": meta.id, "operation": "unique", "column": "nope"})
    assert unknown.startswith("STATUS=INVALID")
    no_filter = csv_inspect.invoke(
        {"upload_id": meta.id, "operation": "filter", "column": "a",
         "params": "a,>,1"})
    assert "Matching rows: 1" in no_filter


def test_csv_inspect_single_column_reports_empty():
    from tools.data_tool import csv_inspect

    meta = _upload_csv(b"word\nhello\nworld\n")
    out = csv_inspect.invoke({"upload_id": meta.id, "operation": "describe"})
    assert out.startswith("STATUS=EMPTY")


# ---------------------------------------------------------------- ODF tools

ODF_CONTENT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<office:document-content '
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'office:version="1.2">'
    "<office:body><office:text>"
    "<text:p>Hello ODF world</text:p>"
    "<text:p>Second paragraph</text:p>"
    "</office:text></office:body></office:document-content>"
).encode("utf-8")


def _odt_bytes(content: bytes = ODF_CONTENT) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.xml", content)
        zf.writestr("mimetype", b"application/vnd.oasis.opendocument.text")
    return buf.getvalue()


def test_read_odt_round_trip():
    from tools.document_tool import read_document

    meta = FileStore("floor-user").save_upload(_odt_bytes(), "notes.odt")
    out = read_document.invoke({"upload_id": meta.id})
    assert "Hello ODF world" in out
    assert "Second paragraph" in out


def test_read_odt_rejects_entities():
    from tools.document_tool import _odf_content_root

    bomb = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]>'
            b"<office:document-content/>")
    with pytest.raises(ValueError, match="entities"):
        _odf_content_root(bomb)


def test_read_odt_missing_content_xml(tmp_path):
    from tools.document_tool import _read_odt_file

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", b"application/vnd.oasis.opendocument.text")
    target = tmp_path / "empty.odt"
    target.write_bytes(buf.getvalue())
    with pytest.raises(ValueError, match="no content.xml"):
        _read_odt_file(str(target))


ODS_CONTENT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<office:document-content '
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'office:version="1.2">'
    "<office:body><office:spreadsheet>"
    '<table:table table:name="Sheet1">'
    "<table:table-row>"
    '<table:table-cell><text:p>A1 cell</text:p></table:table-cell>'
    "</table:table-row>"
    "</table:table>"
    "</office:spreadsheet></office:body></office:document-content>"
).encode("utf-8")

ODP_CONTENT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<office:document-content '
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'office:version="1.2">'
    "<office:body><office:presentation>"
    "<draw:page><text:p>Slide words</text:p></draw:page>"
    "</office:presentation></office:body></office:document-content>"
).encode("utf-8")


def test_read_ods_and_odp_paths(tmp_path):
    from tools.document_tool import _read_ods_file, _read_odp_file

    ods_target = tmp_path / "s.ods"
    ods_target.write_bytes(_odt_bytes(ODS_CONTENT))
    assert "A1 cell" in _read_ods_file(str(ods_target))

    odp_target = tmp_path / "p.odp"
    odp_target.write_bytes(_odt_bytes(ODP_CONTENT))
    assert "Slide words" in _read_odp_file(str(odp_target))


def test_read_document_unknown_id():
    from tools.document_tool import read_document

    out = read_document.invoke({"upload_id": "f" * 16})
    assert out.startswith("STATUS=DENIED")


# ---------------------------------------------------------------- research pure helpers

def _source(url="https://example.com/a", title="Example A"):
    return {"title": title, "url": url, "domain": "example.com"}


def test_validated_brief_sources_filters_and_caps():
    from services.research import validated_brief_sources

    assert validated_brief_sources(None) == []
    assert validated_brief_sources({"sources": "nope"}) == []
    msg = {"sources": [_source()] + [{"url": "javascript:x"}]
           + [_source(f"https://example.com/{i}") for i in range(10)]}
    out = validated_brief_sources(msg)
    assert len(out) == RESEARCH_MAX_SOURCES
    assert all(s["url"].startswith("https://") for s in out)


def test_is_brief_eligible():
    from services.research import is_brief_eligible

    good = {"role": "assistant", "search_executed": True,
            "sources": [_source()]}
    assert is_brief_eligible(good) is True
    assert is_brief_eligible({"role": "user", "search_executed": True,
                              "sources": [_source()]}) is False
    assert is_brief_eligible({"role": "assistant", "sources": [_source()]}) is False
    assert is_brief_eligible({"role": "assistant", "search_executed": True,
                              "sources": []}) is False
    assert is_brief_eligible(None) is False


def test_find_brief_query():
    from services.research import find_brief_query

    messages = [
        {"role": "user", "content": "  research mars rovers  "},
        {"role": "assistant", "content": "answer"},
    ]
    assert find_brief_query(messages, 1) == "research mars rovers"
    assert find_brief_query(messages, 0) is None
    assert find_brief_query("nope", 1) is None
    assert find_brief_query(messages, 99) is None


def test_build_brief_excerpt_bounds():
    from services.research import build_brief_excerpt
    from services.limits import MAX_BRIEF_EXCERPT_CHARS

    assert build_brief_excerpt(None) == ""
    assert build_brief_excerpt("  hi  ") == "hi"
    long_text = "x" * (MAX_BRIEF_EXCERPT_CHARS + 100)
    assert len(build_brief_excerpt(long_text)) == MAX_BRIEF_EXCERPT_CHARS


def test_brief_display_title_and_badges():
    from services.research import (brief_display_title, brief_scope_badge,
                                   brief_source_count, is_brief_in_scope,
                                   is_selected_brief)

    assert brief_display_title(None) == "Untitled brief"
    assert brief_display_title({"query": "mars"}) == "mars"
    assert brief_display_title({"query": "y" * 500}).endswith("…")
    assert brief_scope_badge({}) == "Personal"
    assert brief_scope_badge({"project_id": "p1"}, "Proj") == "Proj"
    assert brief_source_count({"sources": [_source(), {"url": "bad"}]}) == 1
    assert brief_source_count(None) == 0
    assert is_brief_in_scope({"project_id": "p1"}, "p1") is True
    assert is_brief_in_scope({"project_id": "p1"}, None) is False
    assert is_brief_in_scope({}, None) is True
    assert is_selected_brief("a", "a") is True
    assert is_selected_brief("a", "b") is False
    assert is_selected_brief(None, "b") is False


def test_format_brief_created():
    from services.research import format_brief_created

    assert format_brief_created(0) != ""
    assert format_brief_created(None) == ""
    assert format_brief_created("garbage") == ""


def test_sort_artifacts_newest_first():
    from types import SimpleNamespace

    from services.research import sort_artifacts_newest_first

    items = [SimpleNamespace(created=1.0), SimpleNamespace(created=3.0),
             SimpleNamespace(created=2.0)]
    ordered = sort_artifacts_newest_first(items)
    assert [m.created for m in ordered] == [3.0, 2.0, 1.0]
    assert [m.created for m in items] == [1.0, 3.0, 2.0]
    assert sort_artifacts_newest_first(None) == []
