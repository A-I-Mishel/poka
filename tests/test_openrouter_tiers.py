"""OpenRouter fallback tier tests (no network, no quota).

Client construction is lazy (no calls on build); missing key means
the tier is skipped (None). Position: emergency pool — Nemotron Ultra
(curated, user pick) ahead of the Ling VL trial lane (Sep 2026), then
the local Ollama tail. Free Router + GLM 5.2 removed Sep 2026 (local
tier takes the fallback role; GLM failed its trial on rate limits);
Qwen 3.8 27B removed (trial ended, per user request).
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
    assert config.get_tier_openrouter_ultra_llm() is None
    assert config.get_tier_openrouter_ling_vl_llm() is None
    # Removed lanes resolve to None (unknown names).
    assert config.get_tier_llm("OpenRouter Free Router", temperature=0.5) is None
    assert config.get_tier_llm("OpenRouter GLM 5.2", temperature=0.5) is None
    assert config.get_tier_llm("OpenRouter Qwen 27B", temperature=0.5) is None
    assert not hasattr(config, "get_tier_openrouter_glm_llm")
    assert not hasattr(config, "get_tier_openrouter_qwen_llm")
    assert not hasattr(config, "OPENROUTER_QWEN_MODEL")


def test_clients_built_with_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    ultra = config.get_tier_openrouter_ultra_llm()
    ling = config.get_tier_openrouter_ling_vl_llm()
    assert ultra is not None
    assert ling is not None
    assert _model_of(ultra) == config.OPENROUTER_ULTRA_MODEL
    assert _model_of(ling) == config.OPENROUTER_LING_VL_MODEL
    base = getattr(ultra, "openai_api_base", "")
    assert "openrouter.ai" in str(base)


def test_clients_cached(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert config.get_tier_openrouter_ultra_llm() is config.get_tier_openrouter_ultra_llm()
    assert config.get_tier_openrouter_ling_vl_llm() is config.get_tier_openrouter_ling_vl_llm()


def test_model_override(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_LING_VL_MODEL", "inclusionai/custom-override")
    assert _model_of(config.get_tier_openrouter_ling_vl_llm()) == "inclusionai/custom-override"


def test_getter_by_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert config.get_tier_llm("OpenRouter Nemotron Ultra", temperature=0.5) is not None
    assert config.get_tier_llm("OpenRouter Ling VL", temperature=0.5) is not None


def test_cascade_position_is_tail(monkeypatch):
    names = [name for name, _ in config.TIER_GETTERS]
    assert names[-3:] == ["OpenRouter Nemotron Ultra",
                          "OpenRouter Ling VL", "Ollama 8B"]
    assert names[-1] == "Ollama 8B"
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert config.get_tier_llm("OpenRouter Nemotron Ultra", temperature=0.5) is None
    assert config.get_tier_llm("OpenRouter Ling VL", temperature=0.5) is None


def test_provider_table_includes_openrouter():
    from agent import providers

    names = [name for name, _ in providers.TIER_AGENT_GETTERS]
    assert names[-3:] == ["OpenRouter Nemotron Ultra",
                          "OpenRouter Ling VL", "Ollama 8B"]
    assert names[-1] == "Ollama 8B"


def test_ultra_full_synthesis_member():
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]
    assert "OpenRouter Nemotron Ultra" in synth
    assert "OpenRouter Nemotron Ultra" not in cheap


def test_trial_lane_full_synthesis_member():
    """Ling trial lane: full synthesis member, never cheap."""
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]

    assert "OpenRouter Ling VL" in synth
    assert "OpenRouter Ling VL" not in cheap
