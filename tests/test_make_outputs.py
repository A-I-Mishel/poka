"""Make-tool tests: PDF / Markdown / legacy DOC creation + read_output revision.

Hermetic: tmp PLUTO_DATA_DIR, direct stores, real generation tools with
a request-scoped user (no LLM calls). No UI, no network.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services.files import FileStore


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def fenv(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    ctx.set_current_user_id("m-user")
    yield tmp_path / "data"
    ctx.set_current_user_id(None)


SAMPLE_MD = "# Report\n\nSome analysis here.\n\n- point one\n- point two\n"


def test_create_pdf_roundtrip(fenv):
    from pypdf import PdfReader

    from tools.make_tool import create_pdf

    out = create_pdf.invoke({"title": "Q1 Summary", "markdown_text": SAMPLE_MD})
    assert "file ID:" in out and "page" in out
    metas = FileStore("m-user").list_outputs()
    assert len(metas) == 1
    assert metas[0].kind == "pdf"
    assert metas[0].display_name.endswith(".pdf")
    data = FileStore("m-user").read_output(metas[0].id)
    assert data.lstrip().startswith(b"%PDF")
    reader = PdfReader(__import__("io").BytesIO(data))
    assert len(reader.pages) >= 1
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    assert "Q1 Summary" in text and "point one" in text
    spec = metas[0].spec
    assert spec == {
        "kind": "pdf", "tool": "create_pdf",
        "input": {"title": "Q1 Summary", "markdown_text": SAMPLE_MD},
        "created": spec["created"],
    }


def test_create_pdf_rejects_empty(fenv):
    from tools.make_tool import create_pdf

    assert create_pdf.invoke({"title": "", "markdown_text": SAMPLE_MD}).startswith("STATUS=")
    assert create_pdf.invoke({"title": "T", "markdown_text": "   "}).startswith("STATUS=")
    assert create_pdf.invoke({"title": "T", "markdown_text": "# Only"}).startswith("STATUS=")


def test_create_pdf_multipage_and_break(fenv):
    from pypdf import PdfReader

    from tools.make_tool import create_pdf

    body = "\n\n".join(f"## Section {i}\n\nParagraph {i} with some words. " * 4 for i in range(30))
    out = create_pdf.invoke({"title": "Long", "markdown_text": body + "\n\n---\n\nFinal words here."})
    assert "file ID:" in out
    meta = FileStore("m-user").list_outputs()[0]
    reader = PdfReader(__import__("io").BytesIO(FileStore("m-user").read_output(meta.id)))
    assert len(reader.pages) >= 2


def test_create_markdown_roundtrip(fenv):
    from tools.make_tool import create_markdown

    out = create_markdown.invoke({"title": "Notes", "markdown_text": "Just some notes."})
    assert "file ID:" in out
    meta = FileStore("m-user").list_outputs()[0]
    assert meta.kind == "md" and meta.display_name.endswith(".md")
    data = FileStore("m-user").read_output(meta.id).decode("utf-8")
    assert data.startswith("# Notes") and "Just some notes." in data
    assert meta.spec["tool"] == "create_markdown"


def test_create_doc_roundtrip(fenv):
    from tools.make_tool import create_doc

    out = create_doc.invoke({"title": "Letter", "markdown_text": SAMPLE_MD})
    assert "file ID:" in out and "compatible" in out
    meta = FileStore("m-user").list_outputs()[0]
    assert meta.kind == "doc" and meta.display_name.endswith(".doc")
    data = FileStore("m-user").read_output(meta.id).decode("utf-8")
    assert "<html" in data and "Letter" in data and "point one" in data
    assert meta.spec["tool"] == "create_doc"


def test_create_html_roundtrip_fragment(fenv):
    from tools.make_tool import create_html

    out = create_html.invoke({"title": "Landing", "html_content": "<h1>Hello</h1><p>World page.</p>"})
    assert "file ID:" in out and "browser" in out
    meta = FileStore("m-user").list_outputs()[0]
    assert meta.kind == "html" and meta.display_name.endswith(".html")
    data = FileStore("m-user").read_output(meta.id).decode("utf-8")
    assert "<!DOCTYPE html>" in data and "<title>Landing</title>" in data
    assert "Hello" in data and "World page." in data
    assert meta.spec["tool"] == "create_html"


def test_create_html_passthrough_full_document(fenv):
    from tools.make_tool import create_html

    full = "<!DOCTYPE html><html><head><title>Full</title></head><body><p>Kept intact.</p></body></html>"
    out = create_html.invoke({"title": "Full", "html_content": full})
    assert "file ID:" in out
    meta = FileStore("m-user").list_outputs()[0]
    assert FileStore("m-user").read_output(meta.id).decode("utf-8") == full


def test_create_html_rejects_empty(fenv):
    from tools.make_tool import create_html

    assert create_html.invoke({"title": "", "html_content": "<p>x</p>"}).startswith("STATUS=")
    assert create_html.invoke({"title": "T", "html_content": "   "}).startswith("STATUS=")
    assert create_html.invoke({"title": "T", "html_content": "<div><br></div>"}).startswith("STATUS=")


def test_create_html_interactive_js_roundtrip(fenv):
    from tools.make_tool import create_html

    ctx.set_current_user_id("m-html")
    page = ("<!DOCTYPE html><html><head><title>Todo</title></head><body>"
            "<button id='add'>Add</button><ul id='list'></ul>"
            "<script>document.getElementById('add').addEventListener('click',function(){"
            "var li=document.createElement('li');li.textContent='item '+(document.querySelectorAll('#list li').length+1);"
            "document.getElementById('list').appendChild(li);});</script>"
            "</body></html>")
    out = create_html.invoke({"title": "Todo", "html_content": page})
    assert "file ID:" in out and "browser" in out
    meta = FileStore("m-html").list_outputs()[0]
    assert meta.kind == "html"
    data = FileStore("m-html").read_output(meta.id).decode("utf-8")
    assert "<script>" in data and "addEventListener" in data
    assert meta.spec["tool"] == "create_html"


def test_create_html_rejects_unclosed_script(fenv):
    from tools.make_tool import create_html

    ctx.set_current_user_id("m-html")
    out = create_html.invoke({"title": "Broken", "html_content": "<p>Hi</p><script>const x = 1;"})
    assert out.startswith("STATUS=INVALID") and "unclosed <script>" in out


def test_create_html_rejects_truncated_tail(fenv):
    from tools.make_tool import create_html

    ctx.set_current_user_id("m-html")
    cut = ("<!DOCTYPE html><html><head><title>Cut</title></head>"
           "<body><p>Hello</p><div")
    out = create_html.invoke({"title": "Cut", "html_content": cut})
    assert out.startswith("STATUS=INVALID") and "truncated" in out


def test_spec_cleaner_accepts_new_kinds():
    from services.storage import clean_generation_spec

    for kind, tool, keys in [
        ("pdf", "create_pdf", {"title", "markdown_text"}),
        ("md", "create_markdown", {"title", "markdown_text"}),
        ("doc", "create_doc", {"title", "markdown_text"}),
        ("html", "create_html", {"title", "html_content"}),
    ]:
        good = {"kind": kind, "tool": tool,
                "input": {k: "v" for k in keys}, "created": 1.0}
        assert clean_generation_spec(good)["tool"] == tool
    base = {"kind": "pdf", "tool": "create_pdf",
            "input": {"title": "T", "markdown_text": "M"}, "created": 1.0}
    assert clean_generation_spec(dict(base, kind="docx")) is None
    assert clean_generation_spec(dict(base, tool="build_document")) is None


def test_read_output_returns_source(fenv):
    from tools.make_tool import create_markdown, read_output

    out = create_markdown.invoke({"title": "Plan", "markdown_text": "Step one."})
    file_id = out.split("file ID:")[1].strip().rstrip(")")
    text = read_output.invoke({"file_id": file_id})
    assert not text.startswith("STATUS=")
    assert "create_markdown" in text and "Step one." in text and "Plan" in text


def test_read_output_unknown_id(fenv):
    from tools.make_tool import read_output

    assert read_output.invoke({"file_id": "0" * 16}).startswith("STATUS=DENIED")


def test_revise_flow_keeps_original(fenv):
    from tools.make_tool import create_markdown, read_output

    first = create_markdown.invoke({"title": "Plan", "markdown_text": "Step one."})
    first_id = first.split("file ID:")[1].strip().rstrip(")")
    src = read_output.invoke({"file_id": first_id})
    assert "Step one." in src
    second = create_markdown.invoke({"title": "Plan", "markdown_text": "Step one.\nStep two."})
    assert "file ID:" in second
    metas = FileStore("m-user").list_outputs()
    assert len(metas) == 2
    assert {m.id for m in metas} >= {first_id}


def test_regenerate_new_kinds(fenv):
    from services import research as research_svc
    from tools.make_tool import create_doc, create_html, create_markdown, create_pdf

    for invoke_kwargs in [
        lambda: create_pdf.invoke({"title": "R", "markdown_text": SAMPLE_MD}),
        lambda: create_markdown.invoke({"title": "R", "markdown_text": "Body text."}),
        lambda: create_doc.invoke({"title": "R", "markdown_text": SAMPLE_MD}),
        lambda: create_html.invoke({"title": "R", "html_content": "<p>Body text.</p>"}),
    ]:
        before = {m.id for m in FileStore("m-user").list_outputs()}
        invoke_kwargs()
        fresh = [m for m in FileStore("m-user").list_outputs() if m.id not in before][0]
        assert research_svc.can_regenerate(FileStore("m-user"), fresh.id) is True
        new_meta = research_svc.regenerate_artifact(FileStore("m-user"), fresh.id)
        assert new_meta.id != fresh.id
