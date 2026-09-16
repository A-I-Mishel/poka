"""Stateless teaching session: ONE file + 3-slide window, fail-closed."""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _pptx_bytes(slides):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    for texts in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        for i, txt in enumerate(texts):
            tx = slide.shapes.add_textbox(
                Inches(0.5), Inches(0.5 + i), Inches(5), Inches(1)
            )
            tx.text_frame.text = txt
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _ctx(tmp_path, monkeypatch, uid="teach-user"):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", uid)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore

    return UserContext(user_id=uid, user_store=UserStore(uid),
                       file_store=FileStore(uid), limit_key=uid, source="env")


def _fake_agent(monkeypatch, seen):
    import agent as agent_mod

    def _answer(user_input, history=None, **kwargs):
        seen["input"] = str(user_input)
        return {"output": "ok", "active_tier": "Fake",
                "task_type": "research", "tools_used": [], "sources": []}

    monkeypatch.setattr(agent_mod, "answer_with_fallback", _answer)


def test_is_teaching_request():
    from backend.chatflow import _is_teaching_request

    assert _is_teaching_request("teach me these 2 slides one by one") is True
    assert _is_teaching_request("exam tomorrow, teach lecture-wise") is True
    assert _is_teaching_request("hello") is False
    assert _is_teaching_request("tere liye song") is False


def test_continuation_needs_active_session():
    from backend.chatflow import _is_teaching_continuation

    assert _is_teaching_continuation("Next", []) is False
    hist = [{"role": "assistant", "content": "📘 FILE: Lecture_01 — Slides 1-3\nbla\nSay Next for 4-6."}]
    assert _is_teaching_continuation("Next", hist) is True
    assert _is_teaching_continuation("next song", hist) is False
    assert _is_teaching_continuation("x" * 200, hist) is False


def test_router_teaching_never_simple():
    from agent.router import rule_route

    assert rule_route("teach me these 2 slides one by one") in ("research", "multi_step", "creative")
    assert rule_route("teach me these 2 slides one by one") != "simple"
    assert rule_route("exam tomorrow teach graphs") != "simple"
    # "example" must not be hijacked by the exam keyword (exam* stem bug).
    assert rule_route("give me an example sentence") is None


def test_extract_blocks_preserves_numbers(tmp_path, monkeypatch):
    from backend.chatflow import _extract_teaching_blocks

    ctx = _ctx(tmp_path, monkeypatch, "teach-blocks")
    b = _pptx_bytes([["Graph intro"], ["Walk definition"], ["Path definition"], ["Cycle"]])
    meta = ctx.file_store.save_upload(b, "Lecture_01_Graph_Introduction.pptx")
    blocks, total, status = _extract_teaching_blocks(
        ctx, {"id": meta.id, "kind": "document", "name": "Lecture_01_Graph_Introduction.pptx"})
    assert status == "OK"
    assert total == 4
    assert [n for n, _ in blocks] == [1, 2, 3, 4]
    assert "Walk" in blocks[1][1]


def test_teaching_picks_one_file_window(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-one")
    b1 = _pptx_bytes([["L1S1"], ["L1S2"], ["L1S3"], ["L1S4"], ["L1S5"]])
    b2 = _pptx_bytes([["L2S1"], ["L2S2"]])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01_Graph_Introduction.pptx")
    m2 = ctx.file_store.save_upload(b2, "Lecture_02_Practice_Problem_on_Lec_01.pptx")
    atts = [
        {"id": m1.id, "kind": "document", "name": "Lecture_01_Graph_Introduction.pptx"},
        {"id": m2.id, "kind": "document", "name": "Lecture_02_Practice_Problem_on_Lec_01.pptx"},
    ]
    send, vision, clarify = _apply_teaching_session(
        ctx, "teach me these 2 slides one by one", [], atts, [], "teach me")
    assert clarify is None
    # ONE file per batch: first sorted file's CONTENT only (analysis header
    # may name both files with counts, but must not leak L2 slide content).
    assert "Lecture_01" in send
    assert "L2S1" not in send
    assert "L1S1" in send and "L1S3" in send
    assert "L1S4" not in send  # window is 3 slides
    assert "Teaching mode" in send
    assert "Verified content" in send


def test_next_advances_window(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-next")
    b1 = _pptx_bytes([["L1S1"], ["L1S2"], ["L1S3"], ["L1S4"], ["L1S5"]])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01.pptx")
    hist = [
        {"role": "user", "content": "teach me", "attachments": [
            {"id": m1.id, "kind": "document", "name": "Lecture_01.pptx"}]},
        {"role": "assistant", "content": "📘 FILE: Lecture_01.pptx — Slides 1-3\nbla\nSay Next for 4-6."},
    ]
    send, _, _ = _apply_teaching_session(ctx, "Next", hist, [], [], "Next")
    assert "L1S4" in send and "L1S5" in send
    assert "L1S1" not in send


def test_exhausted_file_advances(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-adv")
    b1 = _pptx_bytes([["A1"], ["A2"]])
    b2 = _pptx_bytes([["B1"], ["B2"]])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01.pptx")
    m2 = ctx.file_store.save_upload(b2, "Lecture_02.pptx")
    hist = [
        {"role": "user", "content": "teach", "attachments": [
            {"id": m1.id, "kind": "document", "name": "Lecture_01.pptx"},
            {"id": m2.id, "kind": "document", "name": "Lecture_02.pptx"}]},
        {"role": "assistant", "content": "📘 FILE: Lecture_01.pptx — Slides 1-2\n done."},
    ]
    send, _, _ = _apply_teaching_session(ctx, "Next", hist, [], [], "Next")
    assert "B1" in send  # advanced to second file
    assert "Teaching mode" in send


def test_no_docs_fail_closed(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-empty")
    send, _, clarify = _apply_teaching_session(ctx, "teach me slides", [], [], [], "teach me slides")
    assert clarify is None
    assert "no readable slides" in send.lower()
    assert "Do not invent" in send


def test_run_chat_teaching_injects_window(tmp_path, monkeypatch):
    from backend.chatflow import run_chat

    ctx = _ctx(tmp_path, monkeypatch, "teach-e2e")
    seen = {}
    _fake_agent(monkeypatch, seen)
    b1 = _pptx_bytes([["Graph intro vertex edge"], ["Walk repeats"], ["Path no repeat"], ["Cycle returns"]])
    b2 = _pptx_bytes([["Practice Q1"]])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01_Graph_Introduction.pptx")
    m2 = ctx.file_store.save_upload(b2, "Lecture_02_Practice_Problem_on_Lec_01.pptx")
    run_chat(ctx, "teach me these 2 slides one by one", upload_ids=[m1.id, m2.id])
    assert "Verified content" in seen["input"]
    assert "Teaching mode" in seen["input"]
    assert "Graph intro" in seen["input"]
