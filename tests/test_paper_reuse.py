"""Past-upload reuse: question-paper follow-ups must not dead-end.

"do you have any information on the quesylon paper i uploaded?"
fell through to no-reference -> deny, and the model (with no file
context) told the user to re-upload. Exam-paper phrases route
document-intent; bare past-upload references reuse the only available
modality.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.attachment_gate import decide

DOC = {"id": "doc1", "kind": "pdf", "name": "physics_qp.pdf"}
IMG = {"id": "img1", "kind": "image", "name": "1000034370.jpg"}


def test_question_paper_typo_routes_docs():
    d = decide("do you have any information on the quesylon paper i uploaded?",
               [], [DOC])
    assert [e["id"] for e in d["use_docs"]] == ["doc1"]
    assert d["clarify"] is None


def test_exam_paper_phrases():
    for text in ("explain this exam paper", "solve test paper q1",
                 "from the q paper"):
        d = decide(text, [], [DOC])
        assert d["use_docs"], text


def test_bare_paper_stays_out():
    # "write a paper" is an essay request, not a file reference.
    d = decide("write a paper on graphs", [], [DOC])
    assert d["use_docs"] == []


def test_past_upload_reuses_single_modality():
    d = decide("do you have the file i uploaded?", [], [DOC])
    assert [e["id"] for e in d["use_docs"]] == ["doc1"]
    d = decide("the photo i uploaded yesterday", [IMG], [])
    assert [e["id"] for e in d["use_images"]] == ["img1"]


def test_past_upload_both_modalities_clarifies():
    # No type noun ("the file" alone is doc-explicit and covered
    # elsewhere): genuinely ambiguous past reference clarifies.
    d = decide("info from what i uploaded yesterday", [IMG], [DOC])
    assert d["use_images"] == [] and d["use_docs"] == []
    assert d["clarify"]


def test_the_file_phrase_prefers_docs():
    d = decide("the file i uploaded", [IMG], [DOC])
    assert [e["id"] for e in d["use_docs"]] == ["doc1"]


def test_document_nouns_fall_back_to_image():
    # The 12:19 turn: "not the answer the whole question paper" asked
    # about a photo — doc nouns with only an image available reuse it.
    d = decide("not the answer the whole question paper", [IMG], [])
    assert [e["id"] for e in d["use_images"]] == ["img1"]
    assert d["clarify"] is None


def test_vision_nouns_fall_back_to_doc():
    d = decide("show me the photo again", [], [DOC])
    assert [e["id"] for e in d["use_docs"]] == ["doc1"]


def test_intent_with_nothing_available_falls_through():
    d = decide("not the answer the whole question paper", [], [])
    assert d["use_images"] == [] and d["use_docs"] == []
    # No past-upload phrasing and no files: plain default deny.
    assert d["clarify"] is None


def test_past_upload_phrasing_with_nothing_available_clarifies():
    d = decide("the paper i uploaded", [], [])
    assert d["use_images"] == [] and d["use_docs"] == []
    assert d["clarify"] is not None
    assert "stay with the chat" in d["clarify"]


def test_new_intent_beats_past_upload():
    d = decide("play the song i uploaded", [IMG], [DOC])
    assert d["use_images"] == [] and d["use_docs"] == []
    assert d["clarify"] is None


def test_wire_reuses_doc_in_gate_stage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "paper-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore
    from backend.flow.turns import _apply_attachment_gate

    ctx = UserContext(user_id="paper-user", user_store=UserStore("paper-user"),
                      file_store=FileStore("paper-user"), limit_key="paper-user",
                      source="env")
    hist = [
        {"role": "user", "content": "paper",
         "attachments": [{"id": "doc1", "kind": "pdf", "name": "physics_qp.pdf"}]},
        {"role": "assistant", "content": "got it"},
    ]
    # Registry lookup needs a real upload record; gate works on entries.
    send, vision_ids, clarify = _apply_attachment_gate(
        ctx, "do you have any information on the quesylon paper i uploaded?",
        hist, [], [],
        "do you have any information on the quesylon paper i uploaded?", None)
    # No vault record for doc1 here (deleted/expired), so avail_docs is
    # empty: the past-upload-none clarify explains files stay with their
    # chat instead of a silent deny.
    assert clarify is not None
    assert "stay with the chat" in clarify
    assert isinstance(send, str)
