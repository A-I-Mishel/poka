"""Image-thread follow-ups: disputes/drills reuse the recent image.

"I think ii) is c" carries no image nouns, so decide() default-denies —
yet it references shared Q&A context from the image two turns up. The
follow-up layer reuses the recent image so text tiers answer from the
transcript instead of asking for wording they could read themselves.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.attachment_gate import decide, is_image_followup

IMG = "photo1"


def _hist_with_image(extra=None):
    hist = [
        {"role": "user", "content": "Can you see the image?",
         "attachments": [{"id": IMG, "kind": "image", "name": "1000034370.jpg"}]},
        {"role": "assistant", "content": "ii) B (Not continuous)"},
    ]
    if extra:
        hist.extend(extra)
    return hist


def test_dispute_reuses_recent_image():
    assert is_image_followup("I think ii) is c", _hist_with_image()) == IMG
    assert is_image_followup("are you sure about ii)?", _hist_with_image()) == IMG
    assert is_image_followup("why?", _hist_with_image()) == IMG
    assert is_image_followup("explain option c", _hist_with_image()) == IMG


def test_plain_followup_without_hooks_denied():
    assert is_image_followup("ok thanks", _hist_with_image()) is None
    assert is_image_followup("What is 2+2?", _hist_with_image()) is None


def test_new_intent_wins_over_followup():
    assert is_image_followup("i think play some song", _hist_with_image()) is None
    assert is_image_followup("but first, latest news?", _hist_with_image()) is None


def test_stale_image_denied():
    old = [{"role": "user", "content": "old image",
            "attachments": [{"id": "old1", "kind": "image", "name": "o.png"}]}]
    old += [{"role": "user", "content": f"filler {i}"} for i in range(6)]
    assert is_image_followup("I think ii) is c", old) is None
    assert is_image_followup("I think ii) is c", []) is None


def test_long_message_denied():
    long_text = "I think ii) is c " + ("because reasons " * 20)
    assert len(long_text) > 160
    assert is_image_followup(long_text, _hist_with_image()) is None


def test_gate_still_denies_but_followup_catches():
    # decide() itself is unchanged (default-deny philosophy intact).
    d = decide("I think ii) is c",
               [{"id": IMG, "kind": "image", "name": "1000034370.jpg"}], [])
    assert d["use_images"] == []
    assert is_image_followup("I think ii) is c", _hist_with_image()) == IMG


def test_wire_reuses_image_in_gate_stage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "followup-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore
    from backend.flow.turns import _apply_attachment_gate

    ctx = UserContext(user_id="followup-user", user_store=UserStore("followup-user"),
                      file_store=FileStore("followup-user"), limit_key="followup-user",
                      source="env")
    send, vision_ids, clarify = _apply_attachment_gate(
        ctx, "I think ii) is c", _hist_with_image(), [], [], "I think ii) is c", None)
    assert clarify is None
    assert vision_ids == [IMG]
    assert "sent earlier" in send
