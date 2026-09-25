"""Local Ollama tier tests (no network, no daemon needed).

Single slot = qwen3:8b (synthesis tail, LAST). Cloud quality first,
local offline fallback only. Client construction is lazy (no calls on
build); disabled flag or empty model means the tier is skipped (None).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


def _model_of(client):
    return getattr(client, "model_name", getattr(client, "model", None))


def test_defaults():
    assert config.OLLAMA_MODEL == "qwen3:8b"
    assert not hasattr(config, "OLLAMA_FAST_MODEL")
    assert not hasattr(config, "get_tier_ollama_fast_llm")


def test_disabled_means_skipped(monkeypatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    config._clear_client_cache()
    assert config.get_tier_ollama_llm() is None
    assert config.get_tier_llm("Ollama 8B", temperature=0.5) is None
    assert config.get_tier_llm("Ollama", temperature=0.5) is None


def test_blank_override_falls_back_to_default(monkeypatch):
    """Blank env values are placeholders -> resolve to code defaults (not None)."""
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_MODEL", "   ")
    config._clear_client_cache()
    assert _model_of(config.get_tier_ollama_llm()) == config.OLLAMA_MODEL


def test_empty_code_default_means_skipped(monkeypatch):
    """Empty code default (no override) disables the slot."""
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setattr(config, "OLLAMA_MODEL", "")
    config._clear_client_cache()
    assert config.get_tier_ollama_llm() is None


def test_client_built_with_defaults(monkeypatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    config._clear_client_cache()
    client = config.get_tier_ollama_llm()
    assert client is not None
    assert _model_of(client) == "qwen3:8b"
    base = getattr(client, "openai_api_base", "")
    assert "11434" in str(base)


def test_model_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b-instruct")
    config._clear_client_cache()
    assert _model_of(config.get_tier_ollama_llm()) == "qwen3:8b-instruct"


def test_getter_by_name(monkeypatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    config._clear_client_cache()
    assert config.get_tier_llm("Ollama 8B", temperature=0.5) is not None
    # Legacy alias resolves to the same slot.
    assert config.get_tier_llm("Ollama", temperature=0.5) is not None
    # Removed fast slot resolves to None (unknown name).
    assert config.get_tier_llm("Ollama 4B", temperature=0.5) is None


def test_tail_is_last():
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    fast = [name for name, _ in config.FAST_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]
    # Single local slot sits LAST in both tables: cloud quality first,
    # offline fallback only. Fast stays a subset of synthesis
    # (architectural invariant, see test_fast_tiers).
    assert synth[-1] == "Ollama 8B"
    assert fast[-1] == "Ollama 8B"
    assert "Ollama 8B" not in cheap
    assert "Ollama 4B" not in synth
    assert "Ollama 4B" not in fast
    assert set(n for n, _ in config.FAST_TIERS) < set(synth)


def test_first_token_timeout_per_tier(monkeypatch):
    """Cold Ollama loads get 120s; OpenRouter 20s; default 12s."""
    from agent.executor import _first_token_timeout_for_tier

    monkeypatch.delenv("PLUTO_FIRST_TOKEN_TIMEOUT_OLLAMA", raising=False)
    monkeypatch.delenv("PLUTO_FIRST_TOKEN_TIMEOUT_OPENROUTER", raising=False)
    monkeypatch.delenv("PLUTO_FIRST_TOKEN_TIMEOUT", raising=False)
    assert _first_token_timeout_for_tier("Ollama 8B") == 120.0
    assert _first_token_timeout_for_tier("Ollama") == 120.0
    assert _first_token_timeout_for_tier("OpenRouter Ling VL") == 20.0
    assert _first_token_timeout_for_tier("Groq") == 12.0
    assert _first_token_timeout_for_tier(None) == 12.0


def test_first_token_timeout_ollama_override(monkeypatch):
    from agent.executor import _first_token_timeout_for_tier

    monkeypatch.setenv("PLUTO_FIRST_TOKEN_TIMEOUT_OLLAMA", "30")
    assert _first_token_timeout_for_tier("Ollama 8B") == 30.0
    assert _first_token_timeout_for_tier("Groq") == 12.0
