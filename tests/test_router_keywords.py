"""Router keyword tests: whole-word matching, no substring false positives.

"read" must not match "already", "plot" must not match "exploit",
"search" must not match "research" — while true keywords, stems
("summar*", "analyz*"), and multi-word phrases still route.
"""

import os
import sys

import pytest

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


def test_trivial_routes_unchanged():
    assert rule_route("") == "simple"
    assert rule_route("hello") == "simple"
