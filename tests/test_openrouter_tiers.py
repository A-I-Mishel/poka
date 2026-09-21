"""OpenRouter fallback tier tests (no network, no quota).

Client construction is lazy (no calls on build); missing key means
the tier is skipped (None). Position: emergency pool, just before
Mistral (last resort). Only openrouter/free is kept.
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
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert config.get_tier_openrouter_free_router_llm() is None


def test_clients_built_with_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    router = config.get_tier_openrouter_free_router_llm()
    assert router is not None
    assert _model_of(router) == config.OPENROUTER_FREE_ROUTER_MODEL
    base = getattr(router, "openai_api_base", "")
    assert "openrouter.ai" in str(base)


def test_clients_cached(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert config.get_tier_openrouter_free_router_llm() is config.get_tier_openrouter_free_router_llm()


def test_cascade_position_is_tail(monkeypatch):
    names = [name for name, _ in config.TIER_GETTERS]
    assert names[-2:] == ["OpenRouter Free Router", "Mistral"]
    assert names[-1] == "Mistral"
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert config.get_tier_llm("OpenRouter Free Router", temperature=0.5) is None


def test_provider_table_includes_openrouter():
    from agent import providers

    names = [name for name, _ in providers.TIER_AGENT_GETTERS]
    assert names[-2:] == ["OpenRouter Free Router", "Mistral"]
    assert names[-1] == "Mistral"
