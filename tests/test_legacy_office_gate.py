"""Legacy Office hard-reject: .doc/.ppt/.xls refused at upload (no network).

New uploads of OLE-compound binaries are rejected with conversion
instructions (Save As modern format) instead of silently teaching from
whole-deck blobs with fake [slide 1] citations. Pre-existing vault
files keep best-effort reads; teaching refuses them fail-closed.
"""

import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services.files import FileStore, FileValidationError

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "legacy-gate-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("legacy-gate-user")
    ctx.set_limit_key("legacy-gate-user")
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)


def _ole_payload():
    return _OLE + b"\x00\x00Legacy binary content with enough text padding here\x00\x00"


def _office_zip(member):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, b"<root/>")
    return buf.getvalue()


def test_rejects_ole_doc_ppt_xls_with_instructions():
    cases = (("doc", ".docx", "Word"), ("ppt", ".pptx", "PowerPoint"),
             ("xls", ".xlsx", "Excel"))
    for ext, modern, app in cases:
        with pytest.raises(FileValidationError) as exc:
            FileStore("legacy-gate-user").save_upload(_ole_payload(), f"file.{ext}")
        msg = str(exc.value)
        assert "legacy" in msg and f".{ext}" in msg
        assert "Save As" in msg and modern in msg and app in msg


def test_rejects_ole_disguised_as_modern():
    # OLE bytes wearing a .pptx name: same refusal, disguise wording.
    with pytest.raises(FileValidationError) as exc:
        FileStore("legacy-gate-user").save_upload(_ole_payload(), "deck.pptx")
    assert "despite its name" in str(exc.value)


def test_accepts_genuine_modern_office_and_pdf():
    store = FileStore("legacy-gate-user")
    assert store.save_upload(_office_zip("ppt/presentation.xml"), "deck.pptx")
    assert store.save_upload(_office_zip("word/document.xml"), "report.docx")
    assert store.save_upload(_office_zip("xl/workbook.xml"), "data.xlsx")
    assert store.save_upload(b"%PDF-1.4 hello", "paper.pdf")


def test_teaching_backstop_refuses_legacy_without_model_call(tmp_path, monkeypatch):
    """Pre-existing vault .ppt: fail-closed conversion note, no LLM."""
    from backend.teach import _extract_teaching_blocks

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    from backend.deps import UserContext
    from services.storage import UserStore

    store = FileStore("legacy-gate-user")
    # Simulate a pre-gate vault file: bypass validation like history would.
    monkeypatch.setattr(FileStore, "validate_upload",
                        lambda self, data, filename: "ppt")
    meta = store.save_upload(_ole_payload(), "Old_Lecture.ppt")
    user_ctx = UserContext(user_id="legacy-gate-user",
                           user_store=UserStore("legacy-gate-user"),
                           file_store=store, limit_key="legacy-gate-user",
                           source="env")
    blocks, total, status = _extract_teaching_blocks(
        user_ctx, {"id": meta.id, "kind": "document", "name": "Old_Lecture.ppt"})
    assert blocks == [] and total == 0
    assert status.startswith("STATUS=DENIED")
    assert "Save As" in status and ".pptx" in status
