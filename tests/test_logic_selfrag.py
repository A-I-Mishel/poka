"""Logic checker (local, zero LLM) + lite self-RAG retry. Hermetic, no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import context as ctx


def _invoke(**kwargs):
    from tools.logic_tool import check_logic

    return check_logic.invoke(kwargs)


def test_logic_table_basic():
    out = _invoke(operation="table", formula="p -> q")
    assert "Variables: p, q" in out
    assert "Rows: 4" in out


def test_logic_table_and_or_not():
    out = _invoke(operation="table", formula="(p & q) | !r")
    assert "Rows: 8" in out
    out2 = _invoke(operation="table", formula="p <-> q")
    assert "Rows: 4" in out2


def test_logic_valid_modus_ponens():
    out = _invoke(operation="valid", premises="p -> q\np", conclusion="q")
    assert "VALID" in out


def test_logic_invalid_counterexample():
    out = _invoke(operation="valid", premises="p -> q\nq", conclusion="p")
    assert "INVALID" in out
    assert "Counterexample" in out


def test_logic_bad_syntax():
    out = _invoke(operation="table", formula="p ->")
    assert "STATUS=INVALID" in out
    out2 = _invoke(operation="table", formula="p ( q")
    assert "STATUS=INVALID" in out2
    out3 = _invoke(operation="table", formula="")
    assert "STATUS=INVALID" in out3


def test_logic_unknown_op_and_missing():
    out = _invoke(operation="nope", formula="p")
    assert "STATUS=INVALID" in out
    out2 = _invoke(operation="valid", premises="", conclusion="q")
    assert "STATUS=INVALID" in out2
    out3 = _invoke(operation="valid", premises="p", conclusion="")
    assert "STATUS=INVALID" in out3


def test_logic_too_many_vars():
    out = _invoke(operation="table", formula="a & b & c & d & e & f & g")
    assert "STATUS=INVALID" in out
    assert "too many variables" in out


def test_logic_too_long_and_premises():
    import tools.logic_tool as lt

    long_f = "p & " * 200
    out = _invoke(operation="table", formula=long_f)
    assert "STATUS=INVALID" in out
    many = "\n".join(["p"] * 11)
    out2 = _invoke(operation="valid", premises=many, conclusion="p")
    assert "too many premises" in out2
    assert lt.MAX_LOGIC_VARS == 6


def test_logic_semicolon_premises_and_words():
    out = _invoke(operation="valid", premises="p IMPLIES q; p", conclusion="q")
    assert "VALID" in out
    out2 = _invoke(operation="table", formula="p AND NOT q")
    assert "Rows: 4" in out2


def test_kb_simplified_query():
    from services.kb import simplified_query

    assert simplified_query("what do my documents say about plato") == "plato"
    assert simplified_query("hi") == ""
    assert simplified_query("") == ""


def test_kb_is_weak():
    from services.kb import is_weak_result

    assert is_weak_result([], "what is plato saying here") is True
    assert is_weak_result([{"score": 0.9}], "what is plato saying here") is False
    assert is_weak_result([{"score": 0.1}], "what is plato saying here") is True
    assert is_weak_result([{"score": 1.0}], "what is plato saying here") is True
    assert is_weak_result([{"score": 3.0}], "what is plato saying here") is False
    # short query never retries
    assert is_weak_result([], "hi") is True
    assert is_weak_result([{"score": 0.01}], "plato") is False


def test_search_documents_retry_merge(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    ctx.set_current_user_id("logic-user")
    ctx.set_limit_key("logic-user")
    try:
        import services.kb as kb_mod
        from tools.kb_search_tool import search_documents

        calls = []

        def fake_search(user_id, query, top_k=5, valid_ids=None):
            calls.append(query)
            if query == "what do my documents say about plato":
                return [{"upload_id": "u1", "name": "d1", "chunk": 0, "text": "weak", "score": 0.1}]
            return [{"upload_id": "u2", "name": "d2", "chunk": 1, "text": "plato cave", "score": 0.9}]

        monkeypatch.setattr(kb_mod, "search", fake_search)
        out = search_documents.invoke({"query": "what do my documents say about plato"})
        assert "plato cave" in out
        assert "re-searched with simplified query" in out
        assert len(calls) == 2
    finally:
        ctx.set_current_user_id(None)
        ctx.set_limit_key(None)


def test_search_documents_no_retry_when_strong(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data2"))
    ctx.set_current_user_id("logic-user2")
    ctx.set_limit_key("logic-user2")
    try:
        import services.kb as kb_mod
        from tools.kb_search_tool import search_documents

        calls = []

        def fake_search(user_id, query, top_k=5, valid_ids=None):
            calls.append(query)
            return [{"upload_id": "u1", "name": "d1", "chunk": 0, "text": "strong hit", "score": 0.95}]

        monkeypatch.setattr(kb_mod, "search", fake_search)
        out = search_documents.invoke({"query": "what do my documents say about plato"})
        assert "strong hit" in out
        assert "re-searched" not in out
        assert len(calls) == 1
    finally:
        ctx.set_current_user_id(None)
        ctx.set_limit_key(None)


def test_search_documents_empty_both(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data3"))
    ctx.set_current_user_id("logic-user3")
    ctx.set_limit_key("logic-user3")
    try:
        import services.kb as kb_mod
        from tools.kb_search_tool import search_documents

        monkeypatch.setattr(kb_mod, "search", lambda *a, **k: [])
        out = search_documents.invoke({"query": "what do my documents say about plato"})
        assert "STATUS=EMPTY" in out
    finally:
        ctx.set_current_user_id(None)
        ctx.set_limit_key(None)


def test_tool_registered():
    from agent.toolrun import TOOL_MAP, is_read_only_tool

    assert "check_logic" in TOOL_MAP
    assert is_read_only_tool("check_logic") is True
