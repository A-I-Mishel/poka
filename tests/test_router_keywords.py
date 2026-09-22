"""Router keyword tests: whole-word matching, no substring false positives.

"read" must not match "already", "plot" must not match "exploit",
"search" must not match "research" — while true keywords, stems
("summar*", "analyz*"), and multi-word phrases still route.
"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.router import _signals, rule_route


def test_signals_whole_words():
    assert _signals("please read this", ["read"]) is True
    assert _signals("i already finished", ["read"]) is False
    assert _signals("fresh bread", ["read"]) is False


def test_signals_stems():
    assert _signals("summarize this", ["summar*"]) is True
    assert _signals("a summary please", ["summar*"]) is True
    assert _signals("analyze it", ["analyz*"]) is True
    assert _signals("analyzing the data", ["analyz*"]) is True


def test_signals_phrases_and_extensions():
    assert _signals("look up the capital", ["look up"]) is True
    assert _signals("plot the revenue", ["plot"]) is True
    assert _signals("explain the exploit", ["plot"]) is False
    assert _signals("file.pdf attached", ["pdf", ".pdf"]) is True


def test_no_substring_false_positives():
    assert rule_route("I already finished my homework") is None
    assert rule_route("explain the exploit in that game") is None
    assert rule_route("fix my typewriter") is None
    assert rule_route("research the roman empire") is None


def test_true_keywords_still_route():
    assert rule_route("read this pdf and summarize it") == "research"
    assert rule_route("summarize the document") == "research"
    assert rule_route("search the web for mars") == "research"
    assert rule_route("look up the capital of Peru") == "research"
    assert rule_route("analyze the csv file") == "data"
    assert rule_route("plot the quarterly revenue") == "data"
    assert rule_route("make a presentation about dogs") == "creative"
    assert rule_route("draft an essay") == "creative"
    assert rule_route("latest news today") == "research"


def test_multi_bucket_routes():
    assert rule_route("analyze this csv and make slides") == "multi_step"


def test_entertainment_factual_routes_research():
    assert rule_route("tere liye song") == "research"
    assert rule_route("who sang tere liye") == "research"
    assert rule_route("lyrics of tere liye prince") == "research"
    assert rule_route("cast of veer-zaara") == "research"
    assert rule_route("which movie is this song from") == "research"


def test_songwriting_stays_creative():
    assert rule_route("write a song about Dhaka") == "creative"
    assert rule_route("compose lyrics for my friend") == "creative"


def test_entity_claims_need_verification_prompt():
    from agent.prompts import SYSTEM_PROMPT

    assert "never state credits from memory" in SYSTEM_PROMPT
    assert "[title](url)" in SYSTEM_PROMPT


def test_trivial_routes_unchanged():
    assert rule_route("") == "simple"
    assert rule_route("hello") == "simple"


class _InvokeFake:
    """Minimal invoke-only model double (no streaming, no tools)."""

    def __init__(self, text="hi"):
        self._text = text

    def invoke(self, messages):
        from types import SimpleNamespace

        return SimpleNamespace(content=self._text)


def test_fallthrough_telemetry_scrubs_and_counts():
    from agent import router as router_mod

    router_mod._reset_fallthrough_stats()
    assert router_mod.rule_route("read this pdf") == "research"
    assert router_mod.rule_route("blargh snazzlequix") is None
    assert router_mod.rule_route("Contact bob@exampleXcom about invoice 42") is None
    stats = router_mod.get_fallthrough_stats()
    assert stats["total"] == 3
    assert stats["fallthrough"] == 2
    top = dict(stats["top"])
    assert "blargh snazzlequix" in top
    assert not any("@" in k or "42" in k or "bob" in k for k in top)
    assert any("<n>" in k for k in top)
    router_mod._reset_fallthrough_stats()
    assert router_mod.get_fallthrough_stats() == {"total": 0, "fallthrough": 0, "top": []}


def test_fallthrough_keys_bounded():
    from agent import router as router_mod

    router_mod._reset_fallthrough_stats()
    old_max = router_mod._FALLTHROUGH_MAX_KEYS
    router_mod._FALLTHROUGH_MAX_KEYS = 3
    try:
        for word in ("alpha", "beta", "gamma", "delta"):
            assert router_mod.rule_route(word) is None
        assert len(router_mod.get_fallthrough_stats()["top"]) == 3
    finally:
        router_mod._FALLTHROUGH_MAX_KEYS = old_max
        router_mod._reset_fallthrough_stats()


def test_classifier_failure_falls_back_to_simple(monkeypatch):
    """A dead classifier must pick the cheap direct path, not research."""
    import agent.runtime as runtime

    def _dead_classifier(user_input, llm_instance, budget=None):
        raise RuntimeError("all tiers down for classification")

    monkeypatch.setattr(runtime, "classify_task", _dead_classifier)
    fake = _InvokeFake("hi there")
    out = runtime.answer_with_fallback(
        "what is the meaning of flibbertigibbet?",
        tiers=[("fake", lambda: fake)],
        raw_messages=[],
    )
    assert out["task_type"] == "simple"
    assert out["output"] == "hi there"
    assert out["tools_used"] == []


def _canned_classifier(monkeypatch, text):
    """Double agent._invoke_bounded so classify_task sees canned output."""
    import agent as agent_mod
    from types import SimpleNamespace

    monkeypatch.setattr(
        agent_mod, "_invoke_bounded",
        lambda *a, **k: SimpleNamespace(content=text, tool_calls=[]))


def test_malformed_classifier_output_falls_closed(monkeypatch):
    """Garbage output on plain text must pick simple, not multi_step."""
    from agent.router import classify_task

    for garbage in ("", "Category: simple", "unknown", "SIMPLE.", "simple?"):
        _canned_classifier(monkeypatch, garbage)
        assert classify_task("what is the meaning of life?", None) == "simple"


def test_malformed_classifier_escalates_on_tool_signals(monkeypatch):
    """Garbage output with tool need must still reach multi_step."""
    from agent.router import classify_task

    _canned_classifier(monkeypatch, "uh, dunno??")
    assert classify_task("create a presentation about dogs", None) == "multi_step"
    assert classify_task("compare these", None, has_attachments=True) == "multi_step"
    assert classify_task("compare these", None) == "simple"


def test_valid_classifier_tokens_pass_through(monkeypatch):
    from agent.router import classify_task

    cases = (("  Research ", "research"), ("DATA", "data"),
             ("creative", "creative"), ("multi_step", "multi_step"),
             ("simple", "simple"))
    for raw, want in cases:
        _canned_classifier(monkeypatch, raw)
        assert classify_task("anything", None) == want
