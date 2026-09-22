"""Vision-model OCR fallback tests (no network, no quota, no tesseract).

Covers agent.vision.vision_ocr_bytes (tier iteration + safe defaults),
services.vision.encode_image_bytes (bounds), and the pdf_tool wiring:
scanned pages fall back to vision transcription when on-device OCR is
absent, and the EMPTY message says which engines were tried.
"""

import io
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent.vision as vision_mod
from services.context import set_current_user_id
from services.files import FileStore
from services.vision import encode_image_bytes
from tools import pdf_tool


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
                "CEREBRAS_API_KEY", "OPENCODE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    set_current_user_id("pdf-user")
    yield
    set_current_user_id(None)


def _png_bytes(text="hi", size=(64, 32)):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, "white")
    ImageDraw.Draw(img).text((4, 4), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fake_reader(pages):
    return types.SimpleNamespace(pages=pages)


def _fake_page(text="", images=()):
    return types.SimpleNamespace(
        extract_text=lambda: text,
        images=list(images),
    )


def test_encode_image_bytes_roundtrip():
    url, err = encode_image_bytes(_png_bytes())
    assert err is None
    assert url.startswith("data:image/jpeg;base64,")


def test_encode_image_bytes_rejects_empty_and_garbage():
    url, err = encode_image_bytes(b"")
    assert url is None and err
    url, err = encode_image_bytes(b"not an image at all" * 10)
    assert url is None and "decode" in (err or "")


def test_vision_ocr_returns_empty_without_tiers(monkeypatch):
    monkeypatch.setattr(vision_mod, "_usable_tiers", lambda first, tiers: [])
    assert vision_mod.vision_ocr_bytes(_png_bytes()) == ""


def test_vision_ocr_skips_text_only_tiers(monkeypatch):
    monkeypatch.setattr(
        vision_mod, "_usable_tiers",
        lambda first, tiers: [("Groq", lambda: object())])
    assert vision_mod.vision_ocr_bytes(_png_bytes()) == ""


def test_vision_ocr_transcribes_via_vision_tier(monkeypatch):
    monkeypatch.setattr(
        vision_mod, "_usable_tiers",
        lambda first, tiers: [("Gemini 3.6 Flash", lambda: object())])
    monkeypatch.setattr(
        agent, "_invoke_bounded",
        lambda llm, msgs, **kw: types.SimpleNamespace(content="  Total: 42  "))
    assert vision_mod.vision_ocr_bytes(_png_bytes()) == "Total: 42"


def test_vision_ocr_empty_reply_falls_through(monkeypatch):
    monkeypatch.setattr(
        vision_mod, "_usable_tiers",
        lambda first, tiers: [("Gemini 3.6 Flash", lambda: object())])
    monkeypatch.setattr(
        agent, "_invoke_bounded",
        lambda llm, msgs, **kw: types.SimpleNamespace(content="   "))
    assert vision_mod.vision_ocr_bytes(_png_bytes()) == ""


def test_vision_ocr_never_raises(monkeypatch):
    monkeypatch.setattr(
        vision_mod, "_usable_tiers",
        lambda first, tiers: [("Gemini 3.6 Flash", lambda: (_ for _ in ()).throw(RuntimeError("boom")))])
    assert vision_mod.vision_ocr_bytes(_png_bytes()) == ""
    assert vision_mod.vision_ocr_bytes(b"\x00\x01") == ""


def test_batch_vision_aligns_sections_one_call(monkeypatch):
    calls = []
    monkeypatch.setattr(
        vision_mod, "_usable_tiers",
        lambda first, tiers: [("Gemini 3.6 Flash", lambda: object())])

    def _invoke(llm, msgs, **kw):
        calls.append(1)
        assert len(msgs) == 1
        return types.SimpleNamespace(
            content="IMAGE 1\nAAA\nIMAGE 2\nBBB")

    monkeypatch.setattr(agent, "_invoke_bounded", _invoke)
    out = vision_mod.vision_ocr_many([_png_bytes(), _png_bytes()])
    assert out == ["AAA", "BBB"]
    assert len(calls) == 1


def test_batch_vision_missing_sections_align_empty(monkeypatch):
    monkeypatch.setattr(
        vision_mod, "_usable_tiers",
        lambda first, tiers: [("Gemini 3.6 Flash", lambda: object())])
    monkeypatch.setattr(
        agent, "_invoke_bounded",
        lambda llm, msgs, **kw: types.SimpleNamespace(content="IMAGE 2\nBBB"))
    # IMAGE 1 has no section -> "" (caller falls back per picture).
    assert vision_mod.vision_ocr_many([_png_bytes(), _png_bytes()]) == ["", "BBB"]


def test_batch_vision_skips_unencodable_without_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        vision_mod, "_usable_tiers",
        lambda first, tiers: [("Gemini 3.6 Flash", lambda: object())])
    monkeypatch.setattr(
        agent, "_invoke_bounded",
        lambda llm, msgs, **kw: (calls.append(1),
                                 types.SimpleNamespace(content="IMAGE 1\nAAA"))[1])
    out = vision_mod.vision_ocr_many([b"\x00\x01", _png_bytes()])
    # Garbage blob encodes to nothing (stays ""); the reply's IMAGE 1
    # addresses the first *sent* image, i.e. original index 1.
    assert out == ["", "AAA"]
    assert len(calls) == 1


def test_batch_vision_empty_and_tierless(monkeypatch):
    assert vision_mod.vision_ocr_many([]) == []
    monkeypatch.setattr(vision_mod, "_usable_tiers", lambda first, tiers: [])
    assert vision_mod.vision_ocr_many([_png_bytes()]) == [""]


def test_scanned_pages_use_vision_when_no_tesseract(monkeypatch):
    monkeypatch.setattr(pdf_tool, "_ocr_available", lambda: False)
    monkeypatch.setattr(
        pdf_tool, "_vision_ocr_image_bytes", lambda blob: "vision says hi")
    page = _fake_page("", [types.SimpleNamespace(data=_png_bytes())])
    out = pdf_tool._ocr_scanned_pages(_fake_reader([page]), 1)
    assert "[page 1 vision-OCR]" in out
    assert "vision says hi" in out


def test_scanned_pages_keep_tesseract_label(monkeypatch):
    monkeypatch.setattr(pdf_tool, "_ocr_available", lambda: True)
    monkeypatch.setattr(pdf_tool, "_ocr_image_bytes", lambda blob: "tess text")
    page = _fake_page("", [types.SimpleNamespace(data=b"fake")])
    out = pdf_tool._ocr_scanned_pages(_fake_reader([page]), 1)
    assert "[page 1 OCR]" in out
    assert "vision" not in out


def test_scanned_pages_skip_text_pages(monkeypatch):
    calls = []
    monkeypatch.setattr(pdf_tool, "_ocr_available", lambda: False)
    monkeypatch.setattr(
        pdf_tool, "_vision_ocr_image_bytes",
        lambda blob: calls.append(blob) or "x")
    pages = [_fake_page("native text here", [types.SimpleNamespace(data=b"img")])]
    assert pdf_tool._ocr_scanned_pages(_fake_reader(pages), 1) == ""
    assert calls == []


def _blank_pdf_bytes():
    from pypdf import PdfWriter

    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(612, 792)
    w.write(buf)
    return buf.getvalue()


def test_read_pdf_empty_names_vision_fallback(monkeypatch):
    meta = FileStore("pdf-user").save_upload(_blank_pdf_bytes(), "scan.pdf")
    monkeypatch.setattr(pdf_tool, "_ocr_available", lambda: False)
    monkeypatch.setattr(pdf_tool, "_vision_ocr_image_bytes", lambda blob: "")
    out = pdf_tool.read_pdf.invoke({"upload_id": meta.id})
    assert out.startswith("STATUS=EMPTY")
    assert "scanned" in out
    assert "vision" in out.lower()


def test_read_pdf_vision_transcription_flows_through(monkeypatch):
    meta = FileStore("pdf-user").save_upload(_blank_pdf_bytes(), "scan.pdf")
    monkeypatch.setattr(pdf_tool, "_ocr_available", lambda: False)
    monkeypatch.setattr(
        pdf_tool, "_vision_ocr_image_bytes", lambda blob: "Transcribed line one")
    monkeypatch.setattr(
        pdf_tool, "_looks_scanned", lambda reader, total: True)
    page = _fake_page("", [types.SimpleNamespace(data=_png_bytes())])
    monkeypatch.setattr(
        pdf_tool, "_resolve_reader",
        lambda upload_id: (_fake_reader([page]), 1, None))
    out = pdf_tool.read_pdf.invoke({"upload_id": meta.id})
    assert "Transcribed line one" in out
    assert "vision-model OCR" in out
