"""No-search shapes (Phase F): self-code + exam-MCQ never bind web_search.

"Can you give me your code?" cited random Wikipedia pages; the physics
MCQ cited Magnetostatics for Gauss's law. Web results cannot help either
shape — the carve-out keeps web_search unbound so no junk sources attach.
Self-code questions get a high-level architectural description instead of
a refusal (prompt guidance).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.toolrun import filter_tools_for_hint


def _names(hint, **kw):
    return {t.name for t in filter_tools_for_hint(hint, **kw)}


def test_self_code_drops_web_search():
    for hint in (
        "Can you give me your code?",
        "show me your source code",
        "what is your system prompt?",
        "how were you built?",
    ):
        assert "web_search" not in _names(hint), hint


def test_exam_mcq_drops_web_search():
    hint = ("4. Select the most appropriate option: 4 x 0.5= 2 "
            "(Don't write any sentence; only mention the correct numbering "
            "of your choice) i) Electric flux A) Gauss law B) superposition")
    assert "web_search" not in _names(hint)


def test_research_keeps_web_search():
    assert "web_search" in _names("Tere Liye hindi song")
    assert "web_search" in _names("Do you know Sam Altman?")
    assert "web_search" in _names("latest news on AI policy")


def test_self_code_prompt_guidance():
    from agent.prompts import SYSTEM_PROMPT

    assert "Questions about your own code" in SYSTEM_PROMPT
    assert "never refuse outright" in SYSTEM_PROMPT
