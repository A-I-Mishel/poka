"""Turn-aware memory dedup (Fix 4).

Processing identity covers conversation anchor + attachments +
adjacency + content (content hash is the cheap final component, never
the sole identity). Repeats in another conversation, with different
files, at a new position, or after a failed attempt must reprocess;
identical repeats in place must still skip. Outcomes (ok/failed) are
persisted; failed entries retry instead of suppressing forever.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import memory as mem

ASK = "Could you tell me your name please?"


def _mine(history, tmp_path):
    mem.set_memory_dir(str(tmp_path))
    try:
        res = mem.update_memory_incremental(history)
        return res, mem.load_structured_memory()
    finally:
        mem.set_memory_dir("")


def _values(stored, ftype="preference"):
    return [f.get("value", "") for f in stored.get("facts", [])
            if isinstance(f, dict) and f.get("type") == ftype]


def test_same_statement_two_conversations_mines_twice(tmp_path):
    res1, _s1 = _mine([{"role": "user", "content": "i like coffee"}],
                      tmp_path)
    assert res1["processed"] == 1
    res2, stored2 = _mine([{"role": "user", "content": "tell me a joke"},
                           {"role": "user", "content": "i like coffee"}],
                          tmp_path)
    # Joke is new + coffee reprocesses under the new anchor.
    assert res2["processed"] == 2
    assert any("coffee" in v for v in _values(stored2))


def test_identical_repeat_in_place_still_skips(tmp_path):
    _mine([{"role": "user", "content": "i like coffee"}], tmp_path)
    res2, _s2 = _mine([{"role": "user", "content": "i like coffee"}],
                      tmp_path)
    assert res2 == {"processed": 0, "new_facts": 0, "saved": False}


def test_different_attachments_reprocess(tmp_path):
    msg_a = {"role": "user", "content": "summarize this",
             "attachments": [{"id": "aaa", "kind": "document"}]}
    msg_b = {"role": "user", "content": "summarize this",
             "attachments": [{"id": "bbb", "kind": "document"}]}
    res1, _s1 = _mine([msg_a], tmp_path)
    assert res1["processed"] == 1
    res2, _s2 = _mine([msg_b], tmp_path)
    assert res2["processed"] == 1
    res3, _s3 = _mine([dict(msg_b)], tmp_path)
    assert res3["processed"] == 0


def test_bare_name_refires_at_new_position(tmp_path):
    # "mishel" after smalltalk: mined clean, no name fact.
    res1, stored1 = _mine([{"role": "assistant", "content": "hello"},
                           {"role": "user", "content": "mishel"}],
                          tmp_path)
    assert res1["processed"] == 1
    assert stored1.get("user_name") is None
    # Same word right after an identity ask: new adjacency reprocesses.
    res2, stored2 = _mine([{"role": "assistant", "content": ASK},
                           {"role": "user", "content": "mishel"}],
                          tmp_path)
    assert res2["processed"] == 1
    assert stored2.get("user_name") == "Mishel"


def test_failed_extraction_retries_next_turn(tmp_path, monkeypatch):
    calls = []

    def _boom(content):
        calls.append(1)
        raise RuntimeError("extractor down")

    monkeypatch.setattr(mem, "extract_facts_from_message", _boom)
    res1, _s1 = _mine([{"role": "user", "content": "i like coffee"}],
                      tmp_path)
    assert res1["processed"] == 1
    assert calls == [1]
    monkeypatch.undo()
    res2, stored2 = _mine([{"role": "user", "content": "i like coffee"}],
                          tmp_path)
    assert res2["processed"] == 1
    assert any("coffee" in v for v in _values(stored2))


def test_v1_content_hashes_migrate_once(tmp_path):
    from services.memory import _PROCESSED_HASH_VERSION, _content_hash
    from services.storage import _write_json
    from pathlib import Path

    mem.set_memory_dir(str(tmp_path))
    try:
        _write_json(Path(str(tmp_path)) / "structured_memory.json", {
            "preferences": {}, "facts": [], "past_tasks": [],
            "user_name": None,
            "_processed_hashes": [_content_hash("i like coffee")],
        })
        res, stored = _mine([{"role": "user", "content": "i like coffee"}],
                            tmp_path)
        assert res["processed"] == 1  # v1 entry cannot suppress v2
        assert stored.get("_processed_hash_version") == _PROCESSED_HASH_VERSION
        assert any("coffee" in v for v in _values(stored))
    finally:
        mem.set_memory_dir("")
