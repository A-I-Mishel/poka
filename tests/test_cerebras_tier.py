"""Cerebras free-tier tests (no network, no quota).

Client construction is lazy (no calls on build); a missing or
placeholder key means the tier is skipped (None). Position: between
Groq and Gemini — gpt-oss-120b mirrors the Groq flagship on an
independent backend for dual-homing resilience.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _model_of(client):
    return getattr(client, "model_name", getattr(client, "model", None))


def test_no_key_means_skipped(monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    assert config.get_tier_cerebras_llm() is None


def test_placeholder_key_is_skipped(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "your_cerebras_key_here")
    assert config.get_tier_cerebras_llm() is None


def test_clients_built_with_key(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")
    client = config.get_tier_cerebras_llm()
    assert client is not None
    assert _model_of(client) == config.CEREBRAS_MODEL
    base = getattr(client, "openai_api_base", "")
    assert "cerebras.ai" in str(base)


def test_model_override(monkeypatch):
    # Distinct key value so the (tier, temperature) cache entry is rebuilt.
    monkeypatch.setenv("CEREBRAS_API_KEY", "override-key")
    monkeypatch.setenv("CEREBRAS_MODEL", "zai-glm-4.7")
    assert _model_of(config.get_tier_cerebras_llm()) == "zai-glm-4.7"


def test_clients_cached(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")
    assert config.get_tier_cerebras_llm() is config.get_tier_cerebras_llm()


def test_getter_by_name(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")
    assert config.get_tier_llm("Cerebras", temperature=0.5) is not None


def test_cascade_position_between_groq_and_gemini():
    names = [name for name, _ in config.TIER_GETTERS]
    assert "Cerebras" in names
    assert names.index("Groq") < names.index("Cerebras") < names.index("Gemini 3.6 Flash")


def test_registered_in_agent_table():
    from agent import providers

    names = [name for name, _ in providers.TIER_AGENT_GETTERS]
    assert "Cerebras" in names