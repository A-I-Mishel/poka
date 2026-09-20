"""Display-filtered corrections: UX notes show real typos only.

Phase A: get_corrections() still reports every routing rewrite (used by
the router), but get_display_corrections() — the only source for the
"Interpreted X as Y" UI note — drops routing-internal verb
canonicalizations, capitalized proper nouns, and affix/stemming maps.
Routing itself is byte-identical: teacher still routes teach-intent,
prepare still routes create-intent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.normalize import (
    get_corrections,
    get_display_corrections,
    normalize_text,
)


def test_routing_rewrites_unchanged():
    # Routing truth must not move: these feed intent detection.
    assert "teach" in normalize_text("acting as an teacher").split()
    assert normalize_text("prepare better") == "create better"
    assert normalize_text("build an agent") == "create an agent"
    assert normalize_text("craete a repret").split()[0] == "create"


def test_genuine_typo_still_shown():
    shown = dict(get_display_corrections("craete a repret"))
    assert shown.get("craete") == "create"


def test_verb_canonicalization_never_shown():
    assert get_display_corrections("help me prepare better") == []
    assert get_display_corrections("how to build an omni ai agent") == []
    assert get_display_corrections("turn this into a doc") == []


def test_proper_nouns_never_shown():
    assert get_display_corrections("Tere liye song") == []
    assert get_display_corrections("Its a hindi song") == []
    assert get_display_corrections("Note these points") == []


def test_affix_maps_never_shown():
    assert get_display_corrections("acting as an teacher") == []
    assert get_display_corrections("Can you solve this questions?") == []
    assert get_display_corrections("force on a single charge") == []
    assert get_display_corrections("from these notes") == []


def test_abbreviation_collapse_never_shown():
    # text->txt is a valid word abbreviated, not a typo. Routing still
    # normalizes silently (txt helps doc-intent detection).
    assert get_display_corrections("All visible text in reading order") == []
    assert get_display_corrections("read this text") == []
    assert normalize_text("read this text") == "read this txt"


def test_full_teaching_request_clean():
    shown = get_display_corrections(
        "Hey i have an exam on this topic can you teach me slide by "
        "slide?buy acting as an teacher to help me prepare better in "
        "the exam?"
    )
    assert shown == [], f"unexpected display corrections: {shown}"


def test_omni_agent_request_clean():
    shown = get_display_corrections("Hey fo you know how to builf am omni ai agente.?")
    assert shown == [], f"unexpected display corrections: {shown}"


def test_raw_corrections_still_feed_router():
    # get_corrections keeps reporting routing truth (router confidence
    # uses the display variant separately).
    _, pairs = get_corrections("craete a repret")
    assert ("craete", "create") in pairs


def test_route_confidence_uses_display_pairs():
    from agent.router import get_route_corrections, rule_route_conf

    # Genuine typo: correction-driven route, note attached.
    task, conf = rule_route_conf("craete a repret")
    assert conf == 0.6
    assert dict(get_route_corrections("craete a repret")).get("craete") == "create"
    # False-positive inputs: no display pairs, full confidence, no note.
    for text in (
        "create a doc",
        "Tere liye song",
        "acting as an teacher to help me prepare",
        "Can you solve this questions?",
    ):
        _task, c = rule_route_conf(text)
        if _task is not None and _task != "multi_step":
            assert c > 0.6, f"{text!r} scored {c}"
        assert get_route_corrections(text) == [], f"{text!r} leaked corrections"
