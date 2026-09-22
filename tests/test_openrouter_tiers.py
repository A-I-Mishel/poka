"""OpenRouter fallback tier tests (no network, no quota).

Client construction is lazy (no calls on build); missing key means
the tier is skipped (None). Position: emergency pool — Nemotron Ultra
(curated, user pick) ahead of the Qwen/GLM/Ling trial lanes (Sep 2026),
Ling VL last. Free Router removed Sep 2026 (superseded by local tier).
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
    assert config.get_tier_openrouter_qwen_llm() is None
    assert config.get_tier_openrouter_glm_llm() is None
    assert config.get_tier_openrouter_ling_vl_llm() is None
    # Removed lanes resolve to None (unknown names).
    assert config.get_tier_llm("OpenRouter Free Router", temperature=0.5) is None


def test_clients_built_with_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    ultra = config.get_tier_openrouter_ultra_llm()
    qwen = config.get_tier_openrouter_qwen_llm()
    glm = config.get_tier_openrouter_glm_llm()
    ling = config.get_tier_openrouter_ling_vl_llm()
    assert ultra is not None
    assert qwen is not None and glm is not None and ling is not None
    assert _model_of(ultra) == config.OPENROUTER_ULTRA_MODEL
    assert _model_of(qwen) == config.OPENROUTER_QWEN_MODEL
    assert _model_of(glm) == config.OPENROUTER_GLM_MODEL
    assert _model_of(ling) == config.OPENROUTER_LING_VL_MODEL
    base = getattr(ultra, "openai_api_base", "")
    assert "openrouter.ai" in str(base)


def test_clients_cached(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert config.get_tier_openrouter_ultra_llm() is config.get_tier_openrouter_ultra_llm()
    assert config.get_tier_openrouter_qwen_llm() is config.get_tier_openrouter_qwen_llm()
    assert config.get_tier_openrouter_glm_llm() is config.get_tier_openrouter_glm_llm()
    assert config.get_tier_openrouter_ling_vl_llm() is config.get_tier_openrouter_ling_vl_llm()


def test_model_override(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_QWEN_MODEL", "qwen/custom-override")
    assert _model_of(config.get_tier_openrouter_qwen_llm()) == "qwen/custom-override"


def test_getter_by_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert config.get_tier_llm("OpenRouter Nemotron Ultra", temperature=0.5) is not None
    assert config.get_tier_llm("OpenRouter Qwen 27B", temperature=0.5) is not None
    assert config.get_tier_llm("OpenRouter GLM 5.2", temperature=0.5) is not None
    assert config.get_tier_llm("OpenRouter Ling VL", temperature=0.5) is not None


def test_cascade_position_is_tail(monkeypatch):
    names = [name for name, _ in config.TIER_GETTERS]
    assert names[-4:] == ["OpenRouter Nemotron Ultra", "OpenRouter Qwen 27B",
                          "OpenRouter GLM 5.2", "OpenRouter Ling VL"]
    assert names[-1] == "OpenRouter Ling VL"
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert config.get_tier_llm("OpenRouter Nemotron Ultra", temperature=0.5) is None
    assert config.get_tier_llm("OpenRouter Qwen 27B", temperature=0.5) is None
    assert config.get_tier_llm("OpenRouter GLM 5.2", temperature=0.5) is None
    assert config.get_tier_llm("OpenRouter Ling VL", temperature=0.5) is None


def test_provider_table_includes_openrouter():
    from agent import providers

    names = [name for name, _ in providers.TIER_AGENT_GETTERS]
    assert names[-4:] == ["OpenRouter Nemotron Ultra", "OpenRouter Qwen 27B",
                          "OpenRouter GLM 5.2", "OpenRouter Ling VL"]
    assert names[-1] == "OpenRouter Ling VL"


def test_ultra_full_synthesis_member():
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]
    assert "OpenRouter Nemotron Ultra" in synth
    assert "OpenRouter Nemotron Ultra" not in cheap


def test_trial_lanes_full_synthesis_members():
    """Qwen/GLM/Ling trial lanes: full synthesis members, never cheap."""
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]

    for lane in ("OpenRouter Qwen 27B", "OpenRouter GLM 5.2",
                 "OpenRouter Ling VL"):
        assert lane in synth
        assert lane not in cheap
