"""Local Ollama vision trial tier tests (no network; daemon optional).

Trial slot = qwen2.5vl:3b (vision tail, LAST). Independent kill-switch
(OLLAMA_VL_ENABLED). Client construction is lazy; disabled flag or
empty model means skipped (None). Vision admission is trial-gated in
services/vision.py: only "Ollama VL 3B" sees images. The old text slot
is fully removed (no getter, no model const, no table entries).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


def _model_of(client):
    return getattr(client, "model_name", getattr(client, "model", None))


def test_defaults():
    assert config.OLLAMA_VL_MODEL == "qwen2.5vl:3b"


def test_disabled_means_skipped(monkeypatch):
    monkeypatch.setenv("OLLAMA_VL_ENABLED", "false")
    config._clear_client_cache()
    assert config.get_tier_ollama_vl_llm() is None
    assert config.get_tier_llm("Ollama VL 3B", temperature=0.5) is None
    # Removed text slot resolves to None (unknown names).
    assert config.get_tier_llm("Ollama 7B", temperature=0.5) is None
    assert config.get_tier_llm("Ollama", temperature=0.5) is None
    assert config.get_tier_llm("Ollama 8B", temperature=0.5) is None
    assert not hasattr(config, "get_tier_ollama_llm")
    assert not hasattr(config, "OLLAMA_MODEL")


def test_blank_override_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("OLLAMA_VL_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_VL_MODEL", "   ")
    config._clear_client_cache()
    assert _model_of(config.get_tier_ollama_vl_llm()) == config.OLLAMA_VL_MODEL


def test_client_built_with_defaults(monkeypatch):
    monkeypatch.setenv("OLLAMA_VL_ENABLED", "true")
    monkeypatch.delenv("OLLAMA_VL_MODEL", raising=False)
    config._clear_client_cache()
    client = config.get_tier_ollama_vl_llm()
    assert client is not None
    assert _model_of(client) == "qwen2.5vl:3b"
    base = getattr(client, "openai_api_base", "")
    assert "11434" in str(base)


def test_model_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_VL_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_VL_MODEL", "qwen2.5vl:7b")
    config._clear_client_cache()
    assert _model_of(config.get_tier_ollama_vl_llm()) == "qwen2.5vl:7b"


def test_getter_by_name(monkeypatch):
    monkeypatch.setenv("OLLAMA_VL_ENABLED", "true")
    monkeypatch.delenv("OLLAMA_VL_MODEL", raising=False)
    config._clear_client_cache()
    assert config.get_tier_llm("Ollama VL 3B", temperature=0.5) is not None


def test_tail_is_last():
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    fast = [name for name, _ in config.FAST_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]
    assert synth[-1] == "Ollama VL 3B"
    assert "Ollama VL 3B" not in fast
    assert "Ollama VL 3B" not in cheap


def test_vision_admission_vl_only():
    from services.vision import VISION_TIER_ORDER, vision_supported_tier

    assert VISION_TIER_ORDER[-1] == "Ollama VL 3B"
    assert vision_supported_tier("Ollama VL 3B") is True


def test_first_token_timeout_vl(monkeypatch):
    from agent.executor import _first_token_timeout_for_tier

    monkeypatch.delenv("PLUTO_FIRST_TOKEN_TIMEOUT_OLLAMA", raising=False)
    monkeypatch.delenv("PLUTO_FIRST_TOKEN_TIMEOUT", raising=False)
    assert _first_token_timeout_for_tier("Ollama VL 3B") == 120.0
    assert _first_token_timeout_for_tier("OpenRouter Nemotron Ultra") == 20.0
    assert _first_token_timeout_for_tier("Groq") == 12.0
    assert _first_token_timeout_for_tier(None) == 12.0


def test_first_token_timeout_ollama_override(monkeypatch):
    from agent.executor import _first_token_timeout_for_tier

    monkeypatch.setenv("PLUTO_FIRST_TOKEN_TIMEOUT_OLLAMA", "30")
    assert _first_token_timeout_for_tier("Ollama VL 3B") == 30.0
    assert _first_token_timeout_for_tier("Groq") == 12.0


def test_preferred_vision_tier_defaults_unset():
    from services.context import get_preferred_vision_tier, set_preferred_vision_tier

    assert get_preferred_vision_tier() is None
    set_preferred_vision_tier("Ollama VL 3B")
    assert get_preferred_vision_tier() == "Ollama VL 3B"
    set_preferred_vision_tier(None)
    assert get_preferred_vision_tier() is None


def test_ocr_prefers_pinned_vision_tier(monkeypatch):
    """Pinned VL tier transcribes first; text-only pins are skipped."""
    from types import SimpleNamespace

    import agent.vision as vision_mod
    from services.context import set_preferred_vision_tier

    seen = []

    def _vl():
        seen.append("vl")
        return object()

    def _groq():
        seen.append("groq")
        raise AssertionError("text-only pinned tier must be skipped")

    def _fake_usable(first, tiers):
        order = [("Groq", _groq), ("Ollama VL 3B", _vl)]
        if first == "Ollama VL 3B":
            order.reverse()
        return order

    def _boom(llm, messages, **kwargs):
        return SimpleNamespace(content="transcribed text")

    import agent as agent_mod

    monkeypatch.setattr(vision_mod, "_usable_tiers", _fake_usable)
    monkeypatch.setattr(agent_mod, "_invoke_bounded", _boom)
    monkeypatch.setattr(vision_mod, "encode_image_bytes",
                        lambda blob: ("data:image/png;base64,AAA", None))
    try:
        set_preferred_vision_tier("Ollama VL 3B")
        assert vision_mod.vision_ocr_bytes(b"fake-image-bytes") == "transcribed text"
        assert seen == ["vl"]
        seen.clear()
        set_preferred_vision_tier("Groq")
        assert vision_mod.vision_ocr_bytes(b"fake-image-bytes") == "transcribed text"
        assert seen == ["vl"]
    finally:
        set_preferred_vision_tier(None)
