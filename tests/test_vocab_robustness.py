"""Vocab robustness: verbs (turn/create/convert/make) + typos must route.

Red-first for the senior-dev fix: rule_route() currently misses generic
creation verbs and any typo not in the hard-coded toolrun list.
Desired: creation verbs route creative/multi_step, typos degrade gracefully.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.router import rule_route


def _assert_routes(text, allowed):
    got = rule_route(text)
    assert got in allowed, f"{text!r} routed to {got!r}, expected one of {allowed!r}"


def test_creation_verbs_route_creative():
    # "create/turn/make" alone must imply creative work, not just research via "doc".
    _assert_routes("create a doc", ("creative", "multi_step"))
    _assert_routes("turn this into a doc", ("creative", "multi_step"))
    _assert_routes("make a doc from these notes", ("creative", "multi_step"))
    _assert_routes("convert these notes into a document", ("creative", "multi_step"))
    _assert_routes("build a report from this", ("creative", "multi_step"))


def test_typo_tolerance_keeps_intent():
    # Noun typo + verb intact, or verb typo + noun intact, must not fall through.
    _assert_routes("craete a presentation", ("creative", "multi_step"))
    _assert_routes("craete a repret", ("creative", "multi_step"))
    _assert_routes("convrt this file", ("creative", "multi_step", "research"))
    _assert_routes("fix my pyton", ("data", "multi_step"))
    _assert_routes("summarise this documnet", ("research", "multi_step"))


def test_negatives_still_hold():
    # Whole-word guards must not regress (see test_router_keywords.py).
    assert rule_route("I already finished my homework") is None
    assert rule_route("explain the exploit in that game") is None


def test_route_confidence_and_corrections():
    from agent.router import get_route_corrections, rule_route_conf

    task, conf = rule_route_conf("create a doc")
    assert task in ("creative", "multi_step") and conf >= 0.6
    task_none, conf_none = rule_route_conf("blargh snazzlequix")
    assert task_none is None and conf_none == 0.0
    corr = dict(get_route_corrections("craete a repret"))
    assert corr.get("craete") == "create"
    assert get_route_corrections("hello") == []


def test_tool_binding_covers_typos():
    from agent.toolrun import filter_tools_for_hint

    def _names(hint, **kw):
        return {t.name for t in filter_tools_for_hint(hint, **kw)}

    assert "create_docx" in _names("craete a repret")
    assert "create_docx" in _names("turn this into a doc")
    assert "run_code" in _names("fix my pyton")
    assert "read_document" in _names("summarise this documnet")
    # Tier-aware: GitHub lane drops MCP tools on generic hints.
    assert "list_mcp_tools" not in _names("hello", tier_name="GitHub Models")
    # Creation safety net: intent implies creation family.
    assert "create_pdf" in _names("create something")
