"""Episodic summary preservation (Option A).

Summaries attached at archive time must survive save/load round-trips
instead of being silently dropped by record cleaning. No behavior
change for records without a summary; the summary is stored data only
— nothing injects it into prompts yet.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.storage.cleaners import _clean_chat_record


def _record(**over):
    base = {"id": "a" * 16, "title": "long chat",
            "messages": [{"role": "user", "content": "hi"}],
            "updated_at": "2026-01-01T00:00:00Z"}
    base.update(over)
    return base


def test_summary_preserved_bounded():
    rec = _clean_chat_record(_record(summary="  Early turns discussed X.  "))
    assert rec is not None
    assert rec["summary"] == "Early turns discussed X."


def test_summary_truncated_to_writer_cap():
    rec = _clean_chat_record(_record(summary="s" * 2500))
    assert rec is not None
    assert len(rec["summary"]) == 2000


def test_no_summary_no_field_added():
    rec = _clean_chat_record(_record())
    assert rec is not None
    assert "summary" not in rec


def test_blank_and_nonstr_summary_dropped():
    assert "summary" not in _clean_chat_record(_record(summary="   "))
    assert "summary" not in _clean_chat_record(_record(summary=None))
    assert "summary" not in _clean_chat_record(_record(summary=123))


def test_store_round_trip_keeps_summary(tmp_path, monkeypatch):
    from services.storage import UserStore

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    store = UserStore("summary-user", run_migration=False)
    store.save_chats([_record(summary="Gist of early turns.")], [])
    stored, _warnings = store.load_chats()
    assert stored["chats"][0]["summary"] == "Gist of early turns."
    assert stored["chats"][0]["messages"] == [
        {"role": "user", "content": "hi"}]
