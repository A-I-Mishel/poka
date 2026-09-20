"""Cohere tier: direct-key lane via the OpenAI-compatible endpoint (no network).

Env-gated like the other optional lanes: a missing or placeholder key
means the tier is skipped (None), so unconfigured deploys never notice
it. Position: direct provider after GitHub Models (before the NVIDIA
lane and the OpenRouter aggregator block); full synthesis member.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


def _model_of(client):
    return getattr(client, "model_name", getattr(client, "model", None))


def test_no_key_means_skipped(monkeypatch):
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    assert config.get_tier_cohere_llm() is None


def test_placeholder_key_is_skipped(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "your_cohere_key_here")
    assert config.get_tier_cohere_llm() is None


def test_client_built_with_key(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "test-key")
    client = config.get_tier_cohere_llm()
    assert client is not None
    assert _model_of(client) == config.COHERE_MODEL
    assert "cohere.com" in str(getattr(client, "openai_api_base", ""))


def test_model_override(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "override-key")
    monkeypatch.setenv("COHERE_MODEL", "command-r-08-2024")
    assert _model_of(config.get_tier_cohere_llm()) == "command-r-08-2024"


def test_client_cached(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "test-key")
    assert config.get_tier_cohere_llm() is config.get_tier_cohere_llm()


def test_getter_by_name(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "test-key")
    assert config.get_tier_llm("Cohere", temperature=0.5) is not None


def test_cascade_position():
    names = [name for name, _ in config.TIER_GETTERS]
    assert names.index("GitHub Models") < names.index("Cohere")
    assert names.index("Cohere") < names.index("NVIDIA")
    assert names[-1] == "Mistral"


def test_synthesis_member_cheap_excluded():
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]
    assert "Cohere" in synth
    assert "Cohere" not in cheap


def test_registered_in_agent_table():
    from agent import providers

    names = [name for name, _ in providers.TIER_AGENT_GETTERS]
    assert "Cohere" in names
