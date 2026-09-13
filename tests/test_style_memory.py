"""Style memory tests: extraction, formatting, prompt instruction."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.prompts import SYSTEM_PROMPT
from services import memory as mem


def test_style_extraction_brief():
    facts = mem.extract_facts_from_message("please reply briefly from now on")
    assert any(f["type"] == "style" and "brief" in f["value"] for f in facts), facts


def test_style_extraction_formal():
    facts = mem.extract_facts_from_message("always be formal with me")
    assert any(f["type"] == "style" and "formal" in f["value"] for f in facts), facts
    # "always" upgrades confidence like other facts
    assert any(f.get("confidence") == "high" for f in facts if f["type"] == "style")


def test_style_extraction_none():
    assert [f for f in mem.extract_facts_from_message("what is 2+2?") if f["type"] == "style"] == []


def test_style_formatted_as_data():
    m = {"preferences": {}, "facts": [
        {"type": "style", "value": "prefer brief replies", "polarity": "positive",
         "confidence": "high", "source": "explicit"},
    ], "past_tasks": [], "user_name": None}
    out = mem.format_memory_for_prompt(m)
    assert "Communication style:" in out
    assert "prefer brief replies" in out
    assert "not instructions" in out


def test_system_prompt_matches_style():
    low = SYSTEM_PROMPT.lower()
    assert "same language" in low
    assert "mirror" in low or "formality" in low
    assert "communication style" in low
