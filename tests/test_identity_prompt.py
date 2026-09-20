"""Identity hardening: built prompts forbid claiming provider identity.

Phase B: every answer (full and simple prompts) carries the Pluto-only
identity paragraph, so tiers (especially Gemini) must not answer
"What are you?" with "I am Gemini...". The UI tier suffix carries
routing transparency instead.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.prompts import _build_system_prompt


def _built(simple):
    return _build_system_prompt(
        memory_notes="", relevant_context="", project_context="", simple=simple
    )


def test_full_prompt_has_identity_paragraph():
    prompt = _built(False)
    assert "you are Pluto, not the underlying model" in prompt
    assert "What are you?" in prompt


def test_simple_prompt_has_identity_paragraph():
    prompt = _built(True)
    assert "you are Pluto, not the underlying model" in prompt
    assert "What are you?" in prompt


def test_identity_paragraph_names_no_provider_as_self():
    prompt = _built(False)
    # The paragraph forbids these claims; it must never instruct the
    # model to present itself as a provider ("I am Gemini" bug).
    assert "Never claim to be" in prompt
    assert "I am Gemini" not in prompt
    assert "I am Groq" not in prompt
