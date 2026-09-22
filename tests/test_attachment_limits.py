"""Attachment count validation: excess files fail loudly (Fix 2).

Staging more than MAX_ATTACHMENTS_PER_MESSAGE uploads must raise a
clear ValueError naming the limit — never silently answer from only
the first few files (incomplete comparisons / partial summaries).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.attachments import _resolve_attachments
from services.limits import MAX_ATTACHMENTS_PER_MESSAGE


def _ctx(tmp_path, monkeypatch, uid="limit-user"):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", uid)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore

    return UserContext(user_id=uid, user_store=UserStore(uid),
                       file_store=FileStore(uid), limit_key=uid, source="env")


def _stage(ctx, n):
    ids = []
    for i in range(n):
        meta = ctx.file_store.save_upload(b"limit body %d" % i, "f%d.txt" % i)
        ids.append(meta.id)
    return ids


def test_excess_count_raises_with_limit(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    ids = _stage(ctx, MAX_ATTACHMENTS_PER_MESSAGE + 1)
    with pytest.raises(ValueError, match="At most %d files" % MAX_ATTACHMENTS_PER_MESSAGE):
        _resolve_attachments(ctx, ids)


def test_exact_limit_resolves_all(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    ids = _stage(ctx, MAX_ATTACHMENTS_PER_MESSAGE)
    attachments, _image_ids = _resolve_attachments(ctx, ids)
    assert [a["id"] for a in attachments] == ids


def test_empty_and_duplicate_ids_skipped(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    ids = _stage(ctx, 2)
    attachments, _image_ids = _resolve_attachments(
        ctx, [ids[0], "", ids[0], ids[1], None])
    assert [a["id"] for a in attachments] == ids


def test_unknown_id_still_raises(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Unknown attachment"):
        _resolve_attachments(ctx, ["no-such-upload-id"])


def _hint(ctx, meta):
    from backend.attachments import _attachment_text_hint

    return _attachment_text_hint(
        ctx, {"id": meta.id, "kind": meta.kind, "name": meta.display_name})


def test_corrupt_file_returns_note_not_empty(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    meta = ctx.file_store.save_upload(b"%PDF-1.4\nnot a real pdf", "bad.pdf")
    hint = _hint(ctx, meta)
    assert hint != "", "extract failure must not collapse to an empty hint"
    assert "NOT included" in hint
    assert "read_pdf" in hint
    assert "bad.pdf" in hint


def test_empty_text_returns_note_not_empty(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    meta = ctx.file_store.save_upload(b"   \n  ", "blank.txt")
    hint = _hint(ctx, meta)
    assert hint != ""
    assert "NOT included" in hint
    assert "no extractable text" in hint


def test_oversize_file_returns_note_not_empty(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    meta = ctx.file_store.save_upload(b"x" * (5 * 1024 * 1024 + 1), "big.txt")
    hint = _hint(ctx, meta)
    assert hint != ""
    assert "too large" in hint
    assert "read_document" in hint


def test_deleted_file_returns_note_not_empty(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    meta = ctx.file_store.save_upload(b"gone", "gone.txt")
    ctx.file_store.delete_upload(meta.id)
    hint = _hint(ctx, meta)
    assert hint != ""
    assert "no longer available" in hint


def test_healthy_file_still_inlines(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    meta = ctx.file_store.save_upload(b"hello world notes", "ok.txt")
    hint = _hint(ctx, meta)
    assert "[Content of" in hint and "hello world notes" in hint
    assert "NOT included" not in hint


def test_images_still_bypass_inline(tmp_path, monkeypatch):
    from backend.attachments import _attachment_text_hint

    ctx = _ctx(tmp_path, monkeypatch)
    assert _attachment_text_hint(
        ctx, {"id": "whatever", "kind": "image", "name": "p.png"}) == ""
