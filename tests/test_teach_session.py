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


def test_recall_answer_continues_session():
    from backend.chatflow import _is_teaching_continuation

    hist = [{"role": "assistant",
             "content": "📘 FILE: Lecture_01 — Slides 1-3\nConcept: Graph\nRecall: What is a vertex?\nSay Next for 4-6."}]
    assert _is_teaching_continuation("A vertex is a node", hist) is True
    assert _is_teaching_continuation("next song", hist) is False
    assert _is_teaching_continuation("y" * 400, hist) is False
    # No Recall checkpoint: plain answers do not continue.
    hist2 = [{"role": "assistant", "content": "📘 FILE: Lecture_01 — Slides 1-3\nbla\nSay Next for 4-6."}]
    assert _is_teaching_continuation("A vertex is a node", hist2) is False


def test_admin_block_detection():
    from backend.chatflow import _is_admin_block

    assert _is_admin_block("Course Code CSE 0613-4125 Credit 3.0 Instructor Rubel Sheikh Schedule Mondays") is True
    assert _is_admin_block("Attendance 10% Midterm 20% Final 40%") is True
    assert _is_admin_block("A graph is a pair (V, E) of vertices and edges") is False
    # Mixed definition + course code stays a concept.
    assert _is_admin_block("Graph theory studies graphs. Course CSE 0613-4125 covers the Handshaking theorem") is False


def test_concept_format_in_prompt_and_suffix():
    from agent.prompts import SYSTEM_PROMPT
    from backend.chatflow import TEACHING_SUFFIX

    for token in ("Concept:", "Simple intuition:", "How it works:", "Why:",
                  "Exam importance:", "Exam trap:", "Recall:", "Source: [slide N]"):
        assert token in SYSTEM_PROMPT
        assert token in TEACHING_SUFFIX
    assert "wait for the learner" in SYSTEM_PROMPT.lower()


def test_reflection_teaching_focus():
    from agent.reflection import _TASK_FOCUS

    assert "source fidelity" in _TASK_FOCUS["research"]
    assert "source fidelity" in _TASK_FOCUS["multi_step"]


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


def test_admin_compressed_in_analysis(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-admin")
    b1 = _pptx_bytes([
        ["Course Code CSE 0613-4125 Credit 3.0 Instructor Rubel Sheikh Schedule Mondays"],
        ["Attendance 10 percent Midterm 20 percent Final 40 percent grading policy"],
        ["A graph is a pair V E of vertices and edges"],
        ["Walk repeats vertices edges path cycle degree"],
    ])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01.pptx")
    atts = [{"id": m1.id, "kind": "document", "name": "Lecture_01.pptx"}]
    send, _, _ = _apply_teaching_session(ctx, "teach me slides", [], atts, [], "teach me slides")
    assert "admin" in send.lower()
    assert "Concept:" in send  # new schema mirrored in suffix


def test_practice_quiz_revise_intents():
    from backend.chatflow import _is_teaching_request

    assert _is_teaching_request("quiz me on chapter 3") is True
    assert _is_teaching_request("give me practice problems on these slides") is True
    assert _is_teaching_request("revise lecture 2 notes") is True


def test_router_practice_quiz_research():
    from agent.router import rule_route

    assert rule_route("quiz me on this pdf") == "research"
    assert rule_route("give me practice questions") == "research"


def test_pace_feedback_detection():
    from backend.chatflow import _is_pace_feedback, _pace_direction

    hist = [{"role": "assistant", "content": "📘 FILE: L — Slides 1-3\nConcept: G\nRecall: Q?\nSay Next."}]
    assert _pace_direction("slow down, simpler please") == "slow"
    assert _pace_direction("got it, give harder problems") == "fast"
    assert _pace_direction("what is a vertex") is None
    assert _is_pace_feedback("slow down please", hist) is True
    assert _is_pace_feedback("slow down please", []) is False


def test_pace_note_injected(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-pace")
    b1 = _pptx_bytes([["Graph vertex edge"], ["Walk repeats"], ["Path simple"], ["Cycle closed"]])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01.pptx")
    hist = [
        {"role": "user", "content": "teach me", "attachments": [
            {"id": m1.id, "kind": "document", "name": "Lecture_01.pptx"}]},
        {"role": "assistant", "content": "📘 FILE: Lecture_01.pptx — Slides 1-3\nConcept: G\nRecall: Q?\nSay Next."},
    ]
    send, _, _ = _apply_teaching_session(ctx, "slow down, simpler", hist, [], [], "slow down, simpler")
    assert "slow down" in send.lower()


def test_last_window_section_review(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-review")
    b1 = _pptx_bytes([["Graph vertex edge"], ["Walk repeats"]])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01.pptx")
    atts = [{"id": m1.id, "kind": "document", "name": "Lecture_01.pptx"}]
    send, _, _ = _apply_teaching_session(ctx, "teach me slides", [], atts, [], "teach me slides")
    assert "section review" in send.lower()


def test_exhausted_all_files_exam_mode(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-exammode")
    b1 = _pptx_bytes([["Graph vertex edge"], ["Walk repeats"]])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01.pptx")
    hist = [
        {"role": "user", "content": "teach me", "attachments": [
            {"id": m1.id, "kind": "document", "name": "Lecture_01.pptx"}]},
        {"role": "assistant", "content": "📘 FILE: Lecture_01.pptx — Slides 1-2\nConcept: G\nRecall: Q?"},
    ]
    send, _, _ = _apply_teaching_session(ctx, "Next", hist, [], [], "Next")
    assert "EXAM MODE" in send
    assert "Verified content" not in send


def test_explicit_reteach_skips_exam_mode(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-reteach")
    b1 = _pptx_bytes([["Graph vertex edge"], ["Walk repeats"]])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01.pptx")
    hist = [
        {"role": "user", "content": "teach me", "attachments": [
            {"id": m1.id, "kind": "document", "name": "Lecture_01.pptx"}]},
        {"role": "assistant", "content": "📘 FILE: Lecture_01.pptx — Slides 1-2\nConcept: G\nRecall: Q?"},
    ]
    send, _, _ = _apply_teaching_session(
        ctx, "teach Lecture_01 again", hist, [], [], "teach Lecture_01 again")
    assert "Verified content" in send


def test_subject_templates_in_prompt():
    from agent.prompts import SYSTEM_PROMPT

    assert "line-by-line" in SYSTEM_PROMPT
    assert "compact comparison" in SYSTEM_PROMPT
    assert "missing prerequisite first" in SYSTEM_PROMPT


def test_recall_answer_gets_evaluation_note(tmp_path, monkeypatch):
    from backend.chatflow import _apply_teaching_session

    ctx = _ctx(tmp_path, monkeypatch, "teach-eval")
    b1 = _pptx_bytes([["Graph vertex edge"], ["Walk repeats"], ["Path simple"], ["Cycle closed"]])
    m1 = ctx.file_store.save_upload(b1, "Lecture_01.pptx")
    hist = [
        {"role": "user", "content": "teach me", "attachments": [
            {"id": m1.id, "kind": "document", "name": "Lecture_01.pptx"}]},
        {"role": "assistant", "content": "📘 FILE: Lecture_01.pptx — Slides 1-3\nConcept: Graph\nRecall: What is a vertex?\nSay Next for 4-6."},
    ]
    send, _, _ = _apply_teaching_session(ctx, "A vertex is a node", hist, [], [], "A vertex is a node")
    assert "evaluate" in send.lower()
    assert "Recall checkpoint" in send
