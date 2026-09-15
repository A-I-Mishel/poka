"""Cerebras retired Sep 2026: free tier now payment_required (quota).

Previous free-tier tests kept for history; cascade no longer includes
Cerebras — it was between Groq and Gemini for dual-homing resilience.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_cerebras_retired_from_cascade():
    assert "Cerebras" not in [name for name, _ in config.TIER_GETTERS]
    assert config.get_tier_llm("Cerebras", temperature=0.5) is None


def test_not_in_agent_table():
    from agent import providers

    assert "Cerebras" not in [name for name, _ in providers.TIER_AGENT_GETTERS]
