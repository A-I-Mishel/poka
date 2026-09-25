"""Omni-agent gate: current message decides ACTIVE context (10 cases)."""

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.attachment_gate import decide
from backend.chatflow import regenerate_chat, run_chat


def _ctx(tmp_path, monkeypatch, uid="gate-user"):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", uid)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore

    return UserContext(user_id=uid, user_store=UserStore(uid),
                       file_store=FileStore(uid), limit_key=uid, source="env")


def _png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color="red").save(buf, format="PNG")
    return buf.getvalue()


def _pdf():
    return b"%PDF-1.4\nfake pdf body for gate tests\n" + b"x" * 100


def _txt():
    return b"gate notes body " + b"y" * 50


def _pptx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/slides/slide1.xml", "<slide>hello</slide>")
    return buf.getvalue()


def _fake_agent(monkeypatch, seen):
    import agent as agent_mod

    def _answer(user_input, history=None, **kwargs):
        seen.setdefault("calls", 0)
        seen["calls"] += 1
        seen["image_ids"] = list(kwargs.get("image_upload_ids") or [])
        seen["input"] = str(user_input)
        return {"output": "ok", "active_tier": "Fake",
                "task_type": "simple", "tools_used": [], "sources": []}

    monkeypatch.setattr(agent_mod, "answer_with_fallback", _answer)


def _no_llm(monkeypatch):
    import backend.flow.turns as turns_mod

    def _failing(_tier):
        def _call(_text, _kinds):
            raise RuntimeError("classifier down")
        return _call

    # Patch where _apply_attachment_gate looks it up.
    monkeypatch.setattr(turns_mod, "_attachment_classifier", _failing)


def test_1_single_image_what_is_this(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, "g1")
    meta = ctx.file_store.save_upload(_png(), "shot.png")
    imgs = [{"id": meta.id, "kind": "image", "name": "shot.png"}]
    d = decide("what is this?", imgs, [])
    assert [e["id"] for e in d["use_images"]] == [meta.id]
    assert d["clarify"] is None


def test_2_song_not_vision(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, "g2")
    meta = ctx.file_store.save_upload(_png(), "shot.png")
    seen = {}
    _fake_agent(monkeypatch, seen)
    run_chat(ctx, "(attachment)", upload_ids=[meta.id])
    run_chat(ctx, "tere liye song")
    assert seen["image_ids"] == []
    assert "earlier" not in seen["input"]


def test_3_coding_neither_file(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, "g3")
    img = ctx.file_store.save_upload(_png(), "shot.png")
    pdf = ctx.file_store.save_upload(_pdf(), "paper.pdf")
    seen = {}
    _fake_agent(monkeypatch, seen)
    run_chat(ctx, "(attachment)", upload_ids=[img.id])
    run_chat(ctx, "(attachment)", upload_ids=[pdf.id])
    run_chat(ctx, "write python function to sort a list")
    assert seen["image_ids"] == []
    assert "earlier" not in seen["input"]
    assert img.id not in seen["input"] and pdf.id not in seen["input"]


def test_4_pptx_slide(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, "g4")
    ppt = ctx.file_store.save_upload(_pptx(), "deck.pptx")
    seen = {}
    _fake_agent(monkeypatch, seen)
    run_chat(ctx, "(attachment)", upload_ids=[ppt.id])
    run_chat(ctx, "explain slide 3")
    assert seen["image_ids"] == []
    assert ppt.id in seen["input"]


def test_5_multi_ambiguous_clarifies(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, "g5")
    img = ctx.file_store.save_upload(_png(), "shot.png")
    pdf = ctx.file_store.save_upload(_pdf(), "paper.pdf")
    ppt = ctx.file_store.save_upload(_pptx(), "deck.pptx")
    seen = {}
    _fake_agent(monkeypatch, seen)
    _no_llm(monkeypatch)
    run_chat(ctx, "(attachment)", upload_ids=[img.id])
    run_chat(ctx, "(attachment)", upload_ids=[pdf.id])
    run_chat(ctx, "(attachment)", upload_ids=[ppt.id])
    calls_before = seen.get("calls", 0)
    out = run_chat(ctx, "what is this?")
    assert out["active_tier"] == "clarify"
    assert "image" in out["message"]["content"].lower()
    assert seen.get("calls", 0) == calls_before  # no tier burned


def test_6_pdf_page(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, "g6")
    pdf = ctx.file_store.save_upload(_pdf(), "paper.pdf")
    seen = {}
    _fake_agent(monkeypatch, seen)
    run_chat(ctx, "(attachment)", upload_ids=[pdf.id])
    run_chat(ctx, "explain page 5")
    assert pdf.id in seen["input"]


def test_7_filename_selects_exact(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, "g7")
    img = ctx.file_store.save_upload(_png(), "shot.png")
    txt = ctx.file_store.save_upload(_txt(), "notes.txt")
    seen = {}
    _fake_agent(monkeypatch, seen)
    run_chat(ctx, "(attachment)", upload_ids=[img.id])
    run_chat(ctx, "(attachment)", upload_ids=[txt.id])
    run_chat(ctx, "summarize notes.txt please")
    assert txt.id in seen["input"]
    assert seen["image_ids"] == []


def test_8_regenerate_follows_gate(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, "g8")
    meta = ctx.file_store.save_upload(_png(), "shot.png")
    seen = {}
    _fake_agent(monkeypatch, seen)
    run_chat(ctx, "(attachment)", upload_ids=[meta.id])
    run_chat(ctx, "tere liye song")
    assert seen["image_ids"] == []
    stored, _ = ctx.user_store.load_chats()
    idx = len(stored["current"]) - 1
    regenerate_chat(ctx, idx)
    assert seen["image_ids"] == []


def test_9_classifier_failure_denies_safely():
    img = [{"id": "a" * 16, "kind": "image", "name": "shot.png"}]
    doc = [{"id": "b" * 16, "kind": "pdf", "name": "paper.pdf"}]

    def _boom(_text, _kinds):
        raise RuntimeError("down")

    d = decide("what is this?", img, doc, classifier=_boom)
    assert d["use_images"] == [] and d["use_docs"] == []
    assert d["clarify"] is not None


def test_10_followup_reuse_preserved(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, "g10")
    meta = ctx.file_store.save_upload(_png(), "shot.png")
    seen = {}
    _fake_agent(monkeypatch, seen)
    run_chat(ctx, "(attachment)", upload_ids=[meta.id])
    run_chat(ctx, "can you read the image?")
    assert seen["image_ids"] == [meta.id]
    assert "earlier" in seen["input"]


def test_prompt_current_request_only():
    from agent.prompts import SYSTEM_PROMPT

    assert "always call the matching reader" not in SYSTEM_PROMPT
    assert "explicitly refers to it" in SYSTEM_PROMPT


def test_attachment_classifier_deny_safe(monkeypatch):
    from agent.router import classify_attachment_need

    class _LLM:
        pass

    import agent as agent_mod

    def _boom(llm, msgs, budget=None):
        raise RuntimeError("provider down")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _boom)
    assert classify_attachment_need("what is this?", ["image"], _LLM()) == ("none", 0.0)


def test_classifier_parses_intent():
    from agent.router import classify_attachment_need

    class _Msg:
        content = "intent: vision\nconfidence: 0.9"

    class _LLM:
        pass

    import agent as agent_mod

    orig = agent_mod._invoke_bounded
    agent_mod._invoke_bounded = lambda llm, msgs, budget=None: _Msg()
    try:
        intent, conf = classify_attachment_need("what is this?", ["image"], _LLM())
    finally:
        agent_mod._invoke_bounded = orig
    assert (intent, conf) == ("vision", 0.9)


def test_explicit_new_task_signals():
    """Intent-first gate: creation/export verbs are new tasks, not continuations."""
    from agent.attachment_gate import explicit_new_task

    for text in ("convert the full conversation into a docx file",
                 "create a pdf of these slides",
                 "download this as docx",
                 "export the chat",
                 "generate a presentation about dogs"):
        assert explicit_new_task(text) is True, text
    for text in ("Next", "ok", "A vertex is a node", "summarize this slide",
                 "a graph is created from vertices and edges", ""):
        assert explicit_new_task(text) is False, text


def test_image_followup_yields_to_explicit_task():
    """Image threads obey the same intent-first rule as teaching."""
    from agent.attachment_gate import is_image_followup

    hist = [{"role": "user", "content": "x",
             "attachments": [{"id": "a" * 16, "kind": "image", "name": "s.png"}]},
            {"role": "assistant", "content": "option a is a cat"}]
    assert is_image_followup("convert this chart to pdf", hist) is None
    assert is_image_followup("are you sure?", hist) == "a" * 16
