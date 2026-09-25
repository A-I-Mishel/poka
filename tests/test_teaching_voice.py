"""Teaching voice (humanization mission): 1-slide windows, demo grammar.

Hermetic: pure prompt-data logic, no network, no LLM calls.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_window_is_one_slide():
    from backend import teach as teach_mod

    assert teach_mod.TEACHING_WINDOW_SLIDES == 1
    blocks = [(1, "aaa"), (2, "bbb"), (3, "ccc")]
    window, start, end, truncated = teach_mod._select_teaching_window(blocks, 0)
    assert (start, end) == (1, 1)
    assert [n for n, _ in window] == [1]
    window2, s2, e2, _ = teach_mod._select_teaching_window(blocks, 1)
    assert (s2, e2) == (2, 2)
    assert [n for n, _ in window2] == [2]


def _demo_draft() -> str:
    return (
        "📘 FILE: Lecture_01.pptx\nSlides: 1-1\n"
        "Building on the course intro, here is the first real idea.\n"
        "## Concept: What is a Graph? (Slide 1)\n"
        "A graph is a set of vertices plus a set of edges that relate them.\n"
        "Think objects plus the relationships between them.\n"
        "Imagine:\n```\nA -------- B\n \\       /\n  \\     /\n   C\n```\n"
        "Here:\n- A, B, C = vertices\n- Lines = edges\n"
        "⭐ MUST MEMORIZE\n"
        "Vertex = object/node; Edge = connection/relationship.\n"
        "**Source:** [slide 1]\n"
        "**Recall**\nWhat is the difference between a vertex and an edge?\n"
        "Reply **continue** for the next concept."
    )


def test_demo_style_draft_passes_validation():
    from backend.teach import _validate_teaching_draft

    assert _validate_teaching_draft(_demo_draft(), 1, 1) == []


def test_demo_draft_has_no_robotic_template():
    draft = _demo_draft()
    assert "Exam trap" not in draft
    assert "Exam importance" not in draft
    assert draft.count("**Recall**") == 1
    assert "Imagine:" in draft and "Here:" in draft


def test_admin_compact_passes_without_recall():
    from backend.teach import _validate_teaching_draft

    admin = (
        "📘 FILE: Lecture_01.pptx\nSlides: 1-1\n"
        "### Administrative Information\n"
        "- Course: Graph Theory (CSE 0613-4125)\n- Credit: 3.00\n"
        "**Source:** [slide 1]\n"
        "Nothing technical here. Let's move on."
    )
    assert _validate_teaching_draft(admin, 1, 1) == []


def test_teaching_skips_reflection():
    from agent.reflection import should_reflect

    long_draft = "x" * 500
    teaching_input = "teach me\n\n[Teaching mode: warm human tutor]"
    assert should_reflect("research", long_draft, teaching_input, False) is False
    # Non-teaching research still reflects.
    assert should_reflect("research", long_draft, "plain question", False) is True


def test_fast_tiers_exclude_weakest_lane():
    import config

    fast = [n for n, _ in config.FAST_TIERS]
    synth = [n for n, _ in config.SYNTHESIS_TIERS]
    assert "Ollama 8B" not in fast
    assert "Ollama 8B" in synth  # deep-only offline tail kept
    assert set(fast) < set(synth)


def test_doc_inline_html_renders_and_escapes():
    import html as _html

    from tools.make_tool import _inline_html

    # Contract: caller escapes first, then renders markers.
    out = _inline_html(_html.escape("A **bold** move with <script> and *em* plus `code`"))
    assert "<b>bold</b>" in out
    assert "<i>em</i>" in out
    assert "<code>code</code>" in out
    # Raw HTML is escaped by the caller; only our own tags are markup.
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
