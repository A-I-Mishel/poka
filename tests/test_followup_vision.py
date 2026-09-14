"""Follow-up vision tests: text-only turn reuses recent conversation images."""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.chatflow import _recent_image_ids, run_chat


def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "vision-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore

    user_store = UserStore("vision-user")
    file_store = FileStore("vision-user")
    return UserContext(user_id="vision-user", user_store=user_store,
                       file_store=file_store, limit_key="vision-user",
                       source="env")


def _png_bytes():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color="red").save(buf, format="PNG")
    return buf.getvalue()


def test_recent_image_ids_found(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    meta = ctx.file_store.save_upload(_png_bytes(), "shot.png")
    assert meta.kind == "image"
    msgs = [{"role": "user", "content": "(attachment)",
             "attachments": [{"id": meta.id, "kind": "image", "name": "shot.png"}]},
            {"role": "assistant", "content": "seen"}]
    assert _recent_image_ids(ctx, msgs, []) == [meta.id]


def test_recent_image_ids_empty_without_images(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    assert _recent_image_ids(ctx, [{"role": "user", "content": "hi"}], []) == []


def test_followup_text_reuses_image_for_vision(tmp_path, monkeypatch):
    import agent as agent_mod

    ctx = _ctx(tmp_path, monkeypatch)
    meta = ctx.file_store.save_upload(_png_bytes(), "shot.png")
    seen = {}

    def _answer(user_input, history=None, **kwargs):
        seen["image_ids"] = list(kwargs.get("image_upload_ids") or [])
        seen["input"] = str(user_input)
        return {"output": "I see a red square.", "active_tier": "Gemini 3.6 Flash",
                "task_type": "vision", "tools_used": [], "sources": []}

    monkeypatch.setattr(agent_mod, "answer_with_fallback", _answer)
    # Turn 1: upload with no question.
    run_chat(ctx, "(attachment)", upload_ids=[meta.id])
    # Turn 2: text-only follow-up like the screenshot.
    out = run_chat(ctx, "can you read the image?")
    assert out["active_tier"] == "Gemini 3.6 Flash"
    assert seen["image_ids"] == [meta.id], seen
    assert "earlier" in seen["input"]
