"""Semantic retrieval tests (Slice 2).

Retrieval is pure/deterministic: paraphrase reach comes from Slice 1
canonical keys plus Slice 2 retrieval aliases stored at write time.
No model calls here; the cascade normalizer's alias output is covered
by scripted-_invoke_bounded tests.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import memory as mem


def _bind(tmp_path, facts, user_name=None):
    mem.set_memory_dir(str(tmp_path))
    m = {"preferences": {}, "facts": facts, "past_tasks": [],
         "user_name": user_name}
    assert mem.save_structured_memory(m) is True
    return m


def _unbind():
    mem.set_memory_dir("")


def _dislike_coffee():
    return {"type": "preference", "value": "coffee", "polarity": "negative",
            "confidence": "high", "source": "explicit",
            "key": "dislike: coffee",
            "aliases": ["coffee", "dislike", "espresso"],
            "date": "2026-01-01"}


# --- 1. paraphrase recall -----------------------------------------------------

def test_paraphrased_dislike_retrieved(tmp_path):
    _bind(tmp_path, [_dislike_coffee()])
    try:
        for query in ("i'm not a fan of coffee",
                      "Coffee isn't really my thing",
                      "What have I said about coffee?"):
            out = mem.get_relevant_memory_context(query)
            assert "coffee [dislike]" in out, (query, out)
    finally:
        _unbind()


# --- 2. style recall across wording ---------------------------------------------

def test_style_recall_across_wording(tmp_path):
    _bind(tmp_path, [{
        "type": "style", "value": "prefer brief replies",
        "polarity": "positive", "confidence": "low", "source": "inferred",
        "key": "style: brief", "aliases": ["brief", "concise", "short"],
        "date": "2026-01-01"}])
    try:
        out = mem.get_relevant_memory_context("Keep your answers concise")
        assert "prefer brief replies [style]" in out, out
    finally:
        _unbind()


# --- 3. names keep working ------------------------------------------------------

def test_name_always_injected_and_retrievable(tmp_path):
    _bind(tmp_path, [{
        "type": "name", "value": "Sam", "polarity": "positive",
        "confidence": "high", "source": "explicit", "key": "name: sam",
        "aliases": ["sam", "name"], "date": "2026-01-01"}], user_name="Sam")
    try:
        full = mem.format_memory_for_prompt(mem.load_structured_memory())
        assert "User name: Sam" in full
        out = mem.get_relevant_memory_context("do you remember sam")
        assert "Sam [name]" in out, out
    finally:
        _unbind()


# --- 4. polarity ------------------------------------------------------------------

def test_polarity_correct_and_marked(tmp_path):
    _bind(tmp_path, [_dislike_coffee()])
    try:
        out = mem.get_relevant_memory_context("do i like coffee?")
        assert "coffee [dislike]" in out, out
        assert "[like]" not in out
        vault = mem.load_structured_memory()
        assert vault["facts"][0]["polarity"] == "negative"
    finally:
        _unbind()


# --- 5. related narrowness + top-5 cap ----------------------------------------------

def test_related_does_not_flood(tmp_path):
    _bind(tmp_path, [
        _dislike_coffee(),
        {"type": "preference", "value": "iced coffee", "polarity": "positive",
         "confidence": "low", "source": "inferred", "key": "like: iced coffee",
         "aliases": ["iced", "coffee"], "date": "2026-01-02"},
        {"type": "preference", "value": "tea", "polarity": "positive",
         "confidence": "low", "source": "inferred", "key": "like: tea",
         "aliases": ["tea"], "date": "2026-01-03"},
    ])
    try:
        out = mem.get_relevant_memory_context("i love iced coffee")
        first = out.splitlines()[1]
        assert "iced coffee [like]" in first, out
        out2 = mem.get_relevant_memory_context("tell me about tea")
        assert "tea [like]" in out2 and "[dislike]" not in out2, out2
    finally:
        _unbind()


def test_top_five_cap_kept(tmp_path):
    facts = [{"type": "preference", "value": f"drink{i}",
              "polarity": "positive", "confidence": "low",
              "source": "inferred", "key": f"like: drink{i}",
              "aliases": ["drink"], "date": "2026-01-01"} for i in range(7)]
    _bind(tmp_path, facts)
    try:
        out = mem.get_relevant_memory_context("drink")
        items = [ln for ln in out.splitlines() if ln.startswith("- ")]
        assert len(items) == 5, out
    finally:
        _unbind()


def test_value_match_outranks_alias_only(tmp_path):
    _bind(tmp_path, [
        {"type": "preference", "value": "espresso martini",
         "polarity": "positive", "confidence": "low", "source": "inferred",
         "key": "like: espresso martini", "aliases": ["nightcap"],
         "date": "2026-01-01"},
        _dislike_coffee(),
    ])
    try:
        out = mem.get_relevant_memory_context("coffee")
        lines = [ln for ln in out.splitlines() if ln.startswith("- ")]
        assert lines[0] == "- coffee [dislike]", out
    finally:
        _unbind()


# --- 6. history never retrieved -----------------------------------------------------

def test_history_never_retrieved(tmp_path):
    _bind(tmp_path, [{
        "type": "preference", "value": "espresso", "polarity": "positive",
        "confidence": "low", "source": "inferred", "key": "like: coffee",
        "aliases": ["espresso"], "date": "d1",
        "history": [{"value": "machiato", "polarity": "negative",
                     "date": "d0"}]}])
    try:
        out = mem.get_relevant_memory_context("machiato")
        assert out == "", out
        out2 = mem.get_relevant_memory_context("espresso")
        assert "espresso [like]" in out2 and "machiato" not in out2, out2
    finally:
        _unbind()


# --- 7. legacy keyless memories -------------------------------------------------------

def test_legacy_keyless_recall_unchanged(tmp_path):
    _bind(tmp_path, [{
        "type": "preference", "value": "coffee", "polarity": "negative",
        "confidence": "low", "source": "inferred", "date": "2026-01-01"}])
    try:
        out = mem.get_relevant_memory_context("coffee")
        assert "coffee [dislike]" in out, out
    finally:
        _unbind()


def test_legacy_score_formula_unchanged():
    fact = {"type": "preference", "value": "coffee", "confidence": "low"}
    assert mem._score_fact(fact, {"coffee"}, 0, 1) == 3.0
    assert mem._score_fact(fact, {"tea"}, 0, 1) == 0.0


# --- 8. unrelated queries ---------------------------------------------------------------

def test_unrelated_query_returns_empty(tmp_path):
    _bind(tmp_path, [_dislike_coffee()])
    try:
        assert mem.get_relevant_memory_context("quantum entanglement") == ""
        assert mem.get_relevant_memory_context("   ") == ""
    finally:
        _unbind()


# --- 9. isolation -------------------------------------------------------------------------------

def test_per_user_isolation(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    mem.set_memory_dir(str(dir_a))
    try:
        mem.save_structured_memory({"preferences": {}, "facts": [_dislike_coffee()],
                                    "past_tasks": [], "user_name": None})
    finally:
        _unbind()
    mem.set_memory_dir(str(dir_b))
    try:
        mem.save_structured_memory({"preferences": {}, "facts": [],
                                    "past_tasks": [], "user_name": None})
        assert mem.get_relevant_memory_context("coffee") == ""
    finally:
        _unbind()


# --- 10. read paths never rewrite ----------------------------------------------------------

def test_retrieval_does_not_rewrite_vault(tmp_path):
    import json
    _bind(tmp_path, [_dislike_coffee()])
    try:
        before = json.dumps(mem.load_structured_memory(), sort_keys=True)
        mem.get_relevant_memory_context("not a fan of coffee at all")
        mem.format_memory_for_prompt(mem.load_structured_memory())
        after = json.dumps(mem.load_structured_memory(), sort_keys=True)
        assert before == after
    finally:
        _unbind()


# --- alias hygiene --------------------------------------------------------------------

def test_clean_aliases_caps_and_charset():
    assert mem._clean_aliases(["a", "b", "c", "d", "e", "f"]) == \
        ["a", "b", "c", "d", "e"]
    assert mem._clean_aliases(["  COFFEE!! ", "x" * 60, "", 7, None]) == \
        ["coffee", "x" * 40]
    assert mem._clean_aliases("coffee") == []
    assert mem._clean_aliases(None) == []
    assert mem._clean_aliases(["coffee", "coffee"]) == ["coffee"]


def test_merge_stores_and_adopts_aliases():
    m = {"preferences": {}, "facts": [], "past_tasks": [], "user_name": None}
    norm = {"verdict": "new", "key": "dislike: coffee", "confidence": "low",
            "aliases": ["coffee", "dislike", "espresso", "nope", "never",
                        "extra"]}
    fact = {"type": "preference", "value": "coffee", "polarity": "negative",
            "confidence": "low", "source": "inferred"}
    assert mem._merge_fact(m, fact, norm) is True
    assert m["facts"][0]["aliases"] == ["coffee", "dislike", "espresso",
                                        "nope", "never"]
    assert m["facts"][0]["value"] == "coffee"


# --- normalizer alias parsing -------------------------------------------------------------------

def test_normalizer_aliases_parsed_and_capped(monkeypatch):
    from agent import runtime as rt_mod
    import agent as agent_mod
    from types import SimpleNamespace

    def _invoke(llm, messages, budget=None, **kw):
        return SimpleNamespace(
            content="verdict: new\nkey: dislike: coffee\nconfidence: low\n"
                    "aliases: coffee, dislike, espresso, warm drink, "
                    "morning, extra, junk\n")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    out = rt_mod._normalize_memory_candidate(
        {"type": "preference", "value": "coffee", "polarity": "negative"},
        [], None, None, "test-req", [("Fake", lambda: object())])
    assert out["aliases"] == ["coffee", "dislike", "espresso", "warm drink",
                              "morning"]
    assert out["verdict"] == "new"


def test_normalizer_missing_aliases_line_ok(monkeypatch):
    from agent import runtime as rt_mod
    import agent as agent_mod
    from types import SimpleNamespace

    def _invoke(llm, messages, budget=None, **kw):
        return SimpleNamespace(
            content="verdict: new\nkey: name: sam\nconfidence: high\n")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    out = rt_mod._normalize_memory_candidate(
        {"type": "name", "value": "Sam", "polarity": "positive"},
        [], None, None, "test-req", [("Fake", lambda: object())])
    assert out["verdict"] == "new"
    assert out["aliases"] == []
