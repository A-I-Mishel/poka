"""Exact-format creation: a named format must never be substituted.

Regression: "convert the question paper in pdf" produced a .md file
because the model reached for create_markdown. Tool descriptions now
direct both ways, and the system prompt states the rule once.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_pdf_description_claims_mentions():
    from tools.make_tool import create_pdf

    desc = str(create_pdf.description or "")
    assert "explicitly asks for a PDF" in desc
    assert "create_markdown" in desc
    assert "never substitute" in desc


def test_markdown_description_defers():
    from tools.make_tool import create_markdown

    desc = str(create_markdown.description or "")
    assert "PDF" in desc
    assert "never substitute markdown" in desc


def test_system_prompt_exact_format_rule():
    from agent.prompts import SYSTEM_PROMPT

    assert "never substitute another format" in SYSTEM_PROMPT


def test_creation_binding_still_offers_both():
    from agent.toolrun import filter_tools_for_hint

    names = {t.name for t in filter_tools_for_hint(
        "convert the question paper in pdf")}
    assert "create_pdf" in names
    assert "create_markdown" in names


def test_no_placeholder_links_or_phantom_sources():
    from agent.prompts import SYSTEM_PROMPT

    assert "never invent placeholder links" in SYSTEM_PROMPT
    assert "slide decks" in SYSTEM_PROMPT
