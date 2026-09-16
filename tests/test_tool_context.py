"""Parallel tool execution must preserve the submitting request's user.

Regression test for the production failure where every read-only tool
(read_document, read_pdf, ...) denied with "STATUS=DENIED ... no user
context": _execute_tool_calls_parallel submitted _execute_tool_call to
pool threads, and the user-ID capture happened inside the worker where
contextvars are always empty.
"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _pptx_bytes(lines):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    for i, txt in enumerate(lines):
        tx = slide.shapes.add_textbox(Inches(0.5), Inches(0.5 + i), Inches(5), Inches(1))
        tx.text_frame.text = txt
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_parallel_read_keeps_user_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from services.context import set_current_user_id, set_limit_key
    from services.files import FileStore
    from agent.toolrun import _execute_tool_calls_parallel

    meta = FileStore("ctx-user").save_upload(
        _pptx_bytes(["Hello Parallel"]), "deck.pptx")
    set_current_user_id("ctx-user")
    set_limit_key("ctx-user")
    try:
        out = _execute_tool_calls_parallel(
            [{"name": "read_document", "args": {"upload_id": meta.id}}])
    finally:
        set_current_user_id(None)
        set_limit_key(None)
    assert len(out) == 1
    assert "no user context" not in out[0]
    assert "Hello Parallel" in out[0]


def test_bracket_tool_call_leak_parsed():
    from agent.toolrun import _fallback_tool_calls_from_text

    out = _fallback_tool_calls_from_text(
        'Reading now...\n[Tool call: read_document(upload_id="3f481717bb4f4c7e")]\n---')
    assert out == [{"name": "read_document",
                    "args": {"upload_id": "3f481717bb4f4c7e"}}]


def test_bracket_tool_call_unknown_tool_ignored():
    from agent.toolrun import _fallback_tool_calls_from_text

    assert _fallback_tool_calls_from_text("[Tool call: delete_everything(x=1)]") == []
    assert _fallback_tool_calls_from_text("plain answer, no calls") == []


def test_bracket_and_json_calls_merged():
    from agent.toolrun import _fallback_tool_calls_from_text

    out = _fallback_tool_calls_from_text(
        '[Tool call: read_pdf_page(upload_id="ab12", page=3)] '
        '{"tool": "read_document", "upload_id": "cd34"}')
    assert [c["name"] for c in out] == ["read_pdf_page", "read_document"]
    assert out[0]["args"]["page"] == "3"


def test_parallel_unbound_user_still_denies_safely(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from services.context import set_current_user_id, set_limit_key
    from services.files import FileStore
    from agent.toolrun import _execute_tool_calls_parallel

    meta = FileStore("ctx-user").save_upload(
        _pptx_bytes(["Hello Parallel"]), "deck.pptx")
    set_current_user_id(None)
    set_limit_key(None)
    out = _execute_tool_calls_parallel(
        [{"name": "read_document", "args": {"upload_id": meta.id}}])
    assert "STATUS=DENIED" in out[0]
