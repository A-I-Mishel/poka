"""TokenHarbor fallback tier tests (no network, no quota).

Client construction is lazy (no calls on build); missing key means
the tier is skipped (None). Position: emergency pool tail — MiMo 2.6
Flash (general chat) ahead of DeepSeek V4.1 Flash (reasoning), both
free-allowance trial lanes (Sep 2026, never billed).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


def _model_of(client):
    return getattr(client, "model_name", getattr(client, "model", None))


def test_no_key_means_skipped(monkeypatch):
    monkeypatch.delenv("TOKENHARBOR_API_KEY", raising=False)
    assert config.get_tier_tokenharbor_mimo_llm() is None
    assert config.get_tier_tokenharbor_deepseek_llm() is None
    assert config.get_tier_llm("TokenHarbor Mimo", temperature=0.5) is None
    assert config.get_tier_llm("TokenHarbor DeepSeek", temperature=0.5) is None


def test_clients_built_with_key(monkeypatch):
    monkeypatch.setenv("TOKENHARBOR_API_KEY", "test-key")
    mimo = config.get_tier_tokenharbor_mimo_llm()
    deep = config.get_tier_tokenharbor_deepseek_llm()
    assert mimo is not None and deep is not None
    assert _model_of(mimo) == config.TOKENHARBOR_MIMO_MODEL
    assert _model_of(deep) == config.TOKENHARBOR_DEEPSEEK_MODEL
    base = getattr(mimo, "openai_api_base", "")
    assert "tokenharbor.ai" in str(base)


def test_clients_cached(monkeypatch):
    monkeypatch.setenv("TOKENHARBOR_API_KEY", "test-key")
    assert config.get_tier_tokenharbor_mimo_llm() is config.get_tier_tokenharbor_mimo_llm()
    assert config.get_tier_tokenharbor_deepseek_llm() is config.get_tier_tokenharbor_deepseek_llm()


def test_model_override(monkeypatch):
    monkeypatch.setenv("TOKENHARBOR_API_KEY", "test-key")
    monkeypatch.setenv("TOKENHARBOR_DEEPSEEK_MODEL", "deepseek/custom-override")
    assert _model_of(config.get_tier_tokenharbor_deepseek_llm()) == "deepseek/custom-override"


def test_cascade_position_is_tail():
    names = [name for name, _ in config.TIER_GETTERS]
    assert names[-2:] == ["TokenHarbor Mimo", "TokenHarbor DeepSeek"]
    assert names[-1] == "TokenHarbor DeepSeek"


def test_full_synthesis_members():
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]
    for lane in ("TokenHarbor Mimo", "TokenHarbor DeepSeek"):
        assert lane in synth
        assert lane not in cheap
