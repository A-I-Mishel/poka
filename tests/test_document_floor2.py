"""Hermetic document_tool floor 2: html/zip/rtf/ole/text edge branches.

Covers blocks still at 30% after floor1: _HtmlTextExtractor,
_safe_zip_members, _read_zip_file limits (MAX_ZIP_FILES,
MAX_ZIP_UNCOMPRESSED_BYTES, MAX_ZIP_FILE_BYTES, traversal guard),
_decode_inner_text html branch, _read_rtf_file, _ole_strings_text,
_read_text/html binary guard, unsupported ext, empty/truncate,
size-limit DENIED and OSError FAILED paths.

All via tmp PLUTO_DATA_DIR + FileStore + direct helpers; no network.
"""

import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services.files import FileStore


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "floor2-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("floor2-user")
    ctx.set_limit_key("floor2-user")
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)


# --- HTML extractor direct ---

def test_html_extractor_drops_script_and_keeps_blocks():
    from tools.document_tool import _HtmlTextExtractor

    html = (
        "<html><head><style>body{}</style></head><body>"
        "<script>evil()</script><p>Hello</p><div>World</div>"
        '<a href="https://example.com/a">link</a>'
        "<noscript>hidden</noscript>"
        "</body></html>"
    )
    p = _HtmlTextExtractor()
    p.feed(html)
    p.close()
    out = p.get_text()
    assert "Hello" in out
    assert "World" in out
    assert "evil()" not in out
    # style is also in _SKIP_TAGS -> not leaked
    assert "body{}" not in out


def test_html_file_via_upload():
    from tools.document_tool import read_document

    html = b"<html><body><h1>Title</h1><p>Para one.</p><script>nope</script></body></html>"
    meta = FileStore("floor2-user").save_upload(html, "page.html")
    out = read_document.invoke({"upload_id": meta.id})
    assert "Title" in out
    assert "Para one" in out
    assert "nope" not in out


def test_html_binary_guard(tmp_path):
    from tools.document_tool import _read_html_file

    p = tmp_path / "bad.html"
    p.write_bytes(b"\x00\x01\x02binary")
    with pytest.raises(ValueError, match="binary"):
        _read_html_file(p)


def test_text_binary_guard_and_latin_fallback(tmp_path):
    from tools.document_tool import _read_text_file

    p = tmp_path / "bad.txt"
    p.write_bytes(b"\x00\x01bad")
    with pytest.raises(ValueError, match="binary"):
        _read_text_file(p)

    # latin-1 fallback: byte 0xe9 not valid utf-8 sequence alone but latin-1 decodes to é
    latin = bytes([0xe9, 0x20, 0x68, 0x69])  # "é hi" in latin-1
    p2 = tmp_path / "latin.txt"
    p2.write_bytes(latin)
    out = _read_text_file(p2)
    assert "hi" in out


def test_decode_inner_text_html_branch():
    from tools.document_tool import _decode_inner_text

    blob = b"<p>Hello <b>world</b></p><script>skip</script>"
    out = _decode_inner_text(blob, "page.html")
    assert "Hello" in out
    assert "skip" not in out
    # plain text branch
    assert _decode_inner_text(b"plain text line", "note.txt") == "plain text line"


def test_decode_inner_text_binary_raises():
    from tools.document_tool import _decode_inner_text

    with pytest.raises(ValueError, match="binary"):
        _decode_inner_text(b"\x00\x01binary payload", "a.txt")


# --- _safe_zip_members traversal guard ---

def test_safe_zip_members_filters_traversal_and_dirs(tmp_path):
    from tools.document_tool import _safe_zip_members

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("good.txt", b"ok")
        zf.writestr("../evil.txt", b"evil")
        zf.writestr("/absolute.txt", b"abs")
        zf.writestr("a/../b.txt", b"traversal")
        zf.writestr("dir/", b"")
        zf.writestr("nested/good2.txt", b"ok2")
        # also a ~ prefix
        zf.writestr("~hidden.txt", b"no")
    zf = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    with zf:
        names = [n for _, n in _safe_zip_members(zf)]
    assert "good.txt" in names
    assert "nested/good2.txt" in names
    assert "../evil.txt" not in names
    assert "/absolute.txt" not in names
    assert "dir/" not in names
    assert "~hidden.txt" not in names
    # b.txt from a/../b.txt contains .. part so filtered
    assert "a/../b.txt" not in names


# --- _read_zip_file variants ---

def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_zip_happy_extracts_text_and_skips_binary():
    from tools.document_tool import read_document

    zbytes = _zip_bytes({
        "a.txt": b"hello text",
        "b.html": b"<p>html hello</p>",
        "img.png": b"\x89PNG\x00binary",
    })
    meta = FileStore("floor2-user").save_upload(zbytes, "arch.zip")
    out = read_document.invoke({"upload_id": meta.id})
    assert "[archive arch.zip" in out
    assert "[file a.txt]" in out
    assert "hello text" in out
    assert "html hello" in out
    assert "Skipped non-text members" in out
    assert "img.png" in out


def test_zip_too_many_files_lists_only(monkeypatch):
    from tools.document_tool import _read_zip_file
    import tools.document_tool as dt
    monkeypatch.setattr(dt, "MAX_ZIP_FILES", 2)

    zbytes = _zip_bytes({f"f{i}.txt": b"x" for i in range(5)})
    meta = FileStore("floor2-user").save_upload(zbytes, "many.zip")
    path = FileStore("floor2-user").resolve_upload(meta.id)
    out = _read_zip_file(path)
    assert "showing file list only" in out
    assert "limit 2" in out


def test_zip_uncompressed_too_large_lists_only(monkeypatch):
    from tools.document_tool import _read_zip_file
    import tools.document_tool as dt
    monkeypatch.setattr(dt, "MAX_ZIP_UNCOMPRESSED_BYTES", 10)

    zbytes = _zip_bytes({"a.txt": b"hello world hello world"})
    meta = FileStore("floor2-user").save_upload(zbytes, "big.zip")
    path = FileStore("floor2-user").resolve_upload(meta.id)
    out = _read_zip_file(path)
    assert "too large to expand" in out


def test_zip_per_file_too_large_skipped(monkeypatch):
    from tools.document_tool import _read_zip_file
    import tools.document_tool as dt
    monkeypatch.setattr(dt, "MAX_ZIP_FILE_BYTES", 5)

    zbytes = _zip_bytes({"a.txt": b"1234567890", "b.txt": b"hi"})
    meta = FileStore("floor2-user").save_upload(zbytes, "perfile.zip")
    path = FileStore("floor2-user").resolve_upload(meta.id)
    out = _read_zip_file(path)
    assert "too large" in out
    assert "b.txt" in out or "hi" in out


def test_zip_truncates_member_text_when_budget_exceeded(monkeypatch):
    from tools.document_tool import _read_zip_file
    import tools.document_tool as dt
    monkeypatch.setattr(dt, "MAX_DOCUMENT_CHARS", 20)

    zbytes = _zip_bytes({"a.txt": b"a" * 100, "b.txt": b"b" * 100})
    meta = FileStore("floor2-user").save_upload(zbytes, "trunc.zip")
    path = FileStore("floor2-user").resolve_upload(meta.id)
    out = _read_zip_file(path)
    assert "member text truncated" in out


def test_zip_no_extractable_members_note():
    from tools.document_tool import _read_zip_file

    zbytes = _zip_bytes({"img.png": b"\x89PNGdata", "data.bin": b"\x00\x01\x02"})
    meta = FileStore("floor2-user").save_upload(zbytes, "empty.zip")
    path = FileStore("floor2-user").resolve_upload(meta.id)
    out = _read_zip_file(path)
    assert "no extractable text members found" in out


def test_zip_cannot_open_reports_failed(tmp_path):
    from tools.document_tool import _read_zip_file

    p = tmp_path / "bad.zip"
    p.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="cannot open zip"):
        _read_zip_file(p)


def test_zip_vault_prefix_hidden(tmp_path):
    from tools.document_tool import _read_zip_file

    # FileStore prefixes stored name with 16-hex id, but _read_zip_file hides it in header.
    # We test via direct _read_zip_file on a path whose name looks like <id>_arch.zip
    zbytes = _zip_bytes({"a.txt": b"hi"})
    # Save normally then rename file on disk to vault-like name is hard; instead test the re.match directly
    # by calling _read_zip_file on a Path with vault-like name via tmp_path
    # craft vault-like filename in the pytest tmp dir (no mktemp race)
    vault_name = "abcd1234abcd1234_arch.zip"
    vault_path = tmp_path / vault_name
    vault_path.write_bytes(zbytes)
    out = _read_zip_file(vault_path)
    assert "[archive arch.zip" in out
    vault_path.unlink(missing_ok=True)


# --- RTF ---

RTF_MINIMAL = b"{\\rtf1\\ansi Hello \\par World \\tab test \\'e9 \\emdash end}"


def test_rtf_happy_and_via_upload():
    from tools.document_tool import _read_rtf_file, read_document

    # direct
    tmp = FileStore("floor2-user").save_upload(RTF_MINIMAL, "note.rtf")
    path = FileStore("floor2-user").resolve_upload(tmp.id)
    direct = _read_rtf_file(path)
    assert "Hello" in direct
    assert "World" in direct
    assert "best-effort" in direct

    # via tool
    out = read_document.invoke({"upload_id": tmp.id})
    assert "Hello" in out


def test_rtf_missing_header_fails(tmp_path):
    from tools.document_tool import _read_rtf_file

    p = tmp_path / "bad.rtf"
    p.write_bytes(b"not rtf at all")
    with pytest.raises(ValueError, match="missing"):
        _read_rtf_file(p)


def test_rtf_binary_guard(tmp_path):
    from tools.document_tool import _read_rtf_file

    p = tmp_path / "bin.rtf"
    p.write_bytes(b"\x00\x01\x02rtf")
    with pytest.raises(ValueError, match="binary"):
        _read_rtf_file(p)


def test_rtf_empty_after_strip_fails():
    from tools.document_tool import _read_rtf_file

    # Minimal RTF that strips to empty: only header and control words
    empty_rtf = b"{\\rtf1\\ansi }"
    meta = FileStore("floor2-user").save_upload(empty_rtf, "empty.rtf")
    path = FileStore("floor2-user").resolve_upload(meta.id)
    with pytest.raises(ValueError, match="no extractable text"):
        _read_rtf_file(path)


# --- OLE strings fallback ---

def test_ole_strings_extracts_ascii_and_utf16():
    from tools.document_tool import _ole_strings_text

    ascii_blob = b"\x00\x00HelloWorld from OLE strings extraction is here\x00\x00"
    # UTF16-LE hit: "UTF16Text" as 2-byte LE with null every second byte, need 5+ chars
    utf16_blob = "HELLOUTF16".encode("utf-16-le")
    blob = ascii_blob + b"\x00\x00" + utf16_blob + b"\x00\x00WordDocument\x00"
    out = _ole_strings_text(blob, ".doc")
    assert "HelloWorld" in out
    # junk Root Entry filtered
    assert "Root Entry" not in out
    assert "legacy .doc extracted" in out


def test_ole_strings_long_camel_filtered_and_empty_raises():
    from tools.document_tool import _ole_strings_text

    # long camel without spaces >80 filtered
    long_camel = b"a" * 90
    # junk-only blob -> raises
    with pytest.raises(ValueError, match="no extractable text"):
        _ole_strings_text(b"hi\x00\x00", ".ppt")
    # blob with only long camel -> filtered to empty -> raises
    with pytest.raises(ValueError, match="no extractable text"):
        _ole_strings_text(long_camel + b"\x00", ".doc")


def test_doc_ppt_uploads_rejected_with_conversion_note():
    from services.files import FileValidationError

    # Legacy binaries are hard-refused at upload (conversion instructions,
    # not silent blob teaching) — see tests/test_legacy_office_gate.py.
    ole_magic = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    payload = ole_magic + b"Prefix\x00\x00 MyDocContent Hello World testing OLE fallback more text here \x00\x00"
    for ext in ("doc", "ppt"):
        with pytest.raises(FileValidationError, match="Save As"):
            FileStore("floor2-user").save_upload(payload, f"file.{ext}")


def test_doc_ppt_preexisting_vault_files_still_readable(monkeypatch):
    from tools.document_tool import read_document

    # Pre-gate vault content (validation bypassed like history): the OLE
    # strings fallback keeps working for reads with its fidelity note.
    monkeypatch.setattr(FileStore, "validate_upload",
                        lambda self, data, filename: filename.rsplit(".", 1)[-1].lower())
    ole_magic = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    payload = ole_magic + b"Prefix\x00\x00 MyDocContent Hello World testing OLE fallback more text here \x00\x00"
    for ext in ("doc", "ppt"):
        meta = FileStore("floor2-user").save_upload(payload, f"file.{ext}")
        out = read_document.invoke({"upload_id": meta.id})
        # OLE fallback always carries fidelity note
        assert "MyDocContent" in out or "Hello World" in out
        assert "legacy" in out


def test_xls_fallback_when_xlrd_missing(monkeypatch):
    from tools.document_tool import _read_xls_file

    # Pre-gate vault content (new .xls uploads are refused at validation).
    monkeypatch.setattr(FileStore, "validate_upload",
                        lambda self, data, filename: filename.rsplit(".", 1)[-1].lower())
    # Force pandas path to fail -> fallback to OLE strings (needs OLE magic)
    ole_magic = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    payload = ole_magic + b"XLS fallback content with enough chars to keep HelloWorldXls\x00\x00"
    meta = FileStore("floor2-user").save_upload(payload, "sheet.xls")
    path = FileStore("floor2-user").resolve_upload(meta.id)

    # Monkeypatch pandas.read_excel to raise
    import pandas as pd
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no xlrd")))

    out = _read_xls_file(path)
    assert "HelloWorldXls" in out or "fallback" in out


# --- unsupported ext / empty / truncate / resolve errors ---

def test_unsupported_ext_returns_invalid():
    from tools.document_tool import read_document

    # .png not readable as document -> invalid ext branch
    meta = FileStore("floor2-user").save_upload(b"\x89PNG\r\n\x1a\n", "img.png")
    out = read_document.invoke({"upload_id": meta.id})
    assert out.startswith("STATUS=INVALID")
    assert "not a readable document" in out


def test_empty_text_returns_empty_status():
    from tools.document_tool import read_document

    meta = FileStore("floor2-user").save_upload(b"   \n  ", "empty.txt")
    out = read_document.invoke({"upload_id": meta.id})
    assert out.startswith("STATUS=EMPTY")


def test_truncate_note_at_max_chars(monkeypatch):
    from tools.document_tool import read_document
    import tools.document_tool as dt
    monkeypatch.setattr(dt, "MAX_DOCUMENT_CHARS", 10)

    meta = FileStore("floor2-user").save_upload(b"abcdefghij1234567890", "long.txt")
    out = read_document.invoke({"upload_id": meta.id})
    assert "truncated" in out
    assert len(out) <= 300  # includes note but ensures capped


def test_resolve_size_limit_denied(monkeypatch):
    from tools.document_tool import read_document
    import tools.document_tool as dt
    monkeypatch.setattr(dt, "MAX_UPLOAD_BYTES", 5)

    meta = FileStore("floor2-user").save_upload(b"1234567890", "big.txt")
    out = read_document.invoke({"upload_id": meta.id})
    assert out.startswith("STATUS=DENIED")
    assert "size limit" in out


def test_resolve_stat_oserror(monkeypatch):
    from tools.document_tool import read_document
    # Make path.stat raise OSError via monkeypatch
    meta = FileStore("floor2-user").save_upload(b"hi", "ok.txt")
    orig_resolve = FileStore.resolve_upload

    def fake_resolve(self, uid):
        p = orig_resolve(self, uid)
        # wrap p in object whose stat raises
        class BadPath:
            def __init__(self, real):
                self._real = real
                self.name = real.name
            def __str__(self): return str(self._real)
            def stat(self): raise OSError("disk gone")
            def read_bytes(self): return b"hi"
        return BadPath(p) if p else p

    monkeypatch.setattr(FileStore, "resolve_upload", fake_resolve)
    out = read_document.invoke({"upload_id": meta.id})
    assert out.startswith("STATUS=FAILED")
    assert "cannot stat" in out


# --- ODF extra edges ---

def test_odf_content_root_too_large():
    from tools.document_tool import _odf_content_root

    with pytest.raises(ValueError, match="too large"):
        _odf_content_root(b"x" * (5 * 1024 * 1024 + 1))


def test_odt_no_text_raises(tmp_path):
    from tools.document_tool import _read_odt_file

    # odt with empty body -> no extractable text
    empty_content = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        b'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">'
        b"<office:body><office:text></office:text></office:body></office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("content.xml", empty_content)
    p = tmp_path / "empty.odt"
    p.write_bytes(buf.getvalue())
    with pytest.raises(ValueError, match="no extractable text"):
        _read_odt_file(str(p))


def test_odt_content_xml_too_large_field(tmp_path):
    from tools.document_tool import _read_odt_file

    # Trick: set ZipInfo file_size large via writing then monkeypatch getinfo? Simpler: test the guard by
    # constructing a zip where content.xml exceeds 5MB header check via mocking ZipInfo
    # Instead we test via direct call with oversized blob header: patch ZipFile.getinfo to return large file_size
    real_bytes = b"small"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("content.xml", real_bytes)
    # monkeypatch ZipFile to return inflated file_size
    orig_getinfo = zipfile.ZipFile.getinfo
    def fake_getinfo(self, name):
        info = orig_getinfo(self, name)
        info.file_size = 6 * 1024 * 1024
        return info
    import unittest.mock as mock
    p = tmp_path / "large.odt"
    p.write_bytes(buf.getvalue())
    with mock.patch.object(zipfile.ZipFile, "getinfo", fake_getinfo):
        with pytest.raises(ValueError, match="too large"):
            _read_odt_file(str(p))


def test_ods_cannot_open(monkeypatch, tmp_path):
    from tools.document_tool import _read_ods_file

    p = tmp_path / "bad.ods"
    p.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="cannot open ods"):
        _read_ods_file(str(p))


def test_odp_no_text_raises(tmp_path):
    from tools.document_tool import _read_odp_file

    empty_content = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        b'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        b'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" office:version="1.2">'
        b"<office:body><office:presentation></office:presentation></office:body></office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("content.xml", empty_content)
    p = tmp_path / "empty.odp"
    p.write_bytes(buf.getvalue())
    with pytest.raises(ValueError, match="no extractable text"):
        _read_odp_file(str(p))
