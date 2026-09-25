"""Kilo Gateway tier tests (no network, no quota).

Client construction is lazy (no calls on build); the lane is keyless
by design (:free models accept anonymous requests), so no env key is
ever required. Position: emergency pool — behind OpenRouter Nemotron
Ultra, ahead of the local Ollama tail. Synthesis-only (never cheap,
never fast, never vision: text-only until a vision trial).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


def _model_of(client):
    return getattr(client, "model_name", getattr(client, "model", None))


def test_keyless_always_builds(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    assert config.get_tier_kilo_dots_llm() is not None


def test_client_points_at_kilo_gateway():
    dots = config.get_tier_kilo_dots_llm()
    assert dots is not None
    assert _model_of(dots) == config.KILO_DOTS_MODEL
    assert config.KILO_DOTS_MODEL == "dots-studio/dots-3-note-preview:free"
    base = getattr(dots, "openai_api_base", "")
    assert "api.kilo.ai" in str(base)


def test_model_override_env(monkeypatch):
    monkeypatch.setenv("KILO_DOTS_MODEL", "some/other:free")
    dots = config.get_tier_kilo_dots_llm()
    assert dots is not None
    assert _model_of(dots) == "some/other:free"


def test_clients_cached():
    assert config.get_tier_kilo_dots_llm() is config.get_tier_kilo_dots_llm()


def test_getter_by_name():
    assert config.get_tier_llm("Kilo Dots 3 Note", temperature=0.5) is not None


def test_no_authorization_header_sent():
    """Anonymous lane: built requests carry no Bearer (dummy is rejected)."""
    from openai._base_client import FinalRequestOptions

    llm = config.get_tier_kilo_dots_llm()
    assert llm is not None
    opts = FinalRequestOptions.construct(
        method="post",
        url="/chat/completions",
        json_data={"model": "x", "messages": []},
    )
    headers = dict(llm.root_client._build_request(opts).headers)
    assert "authorization" not in {k.lower() for k in headers}


def test_cascade_position_is_tail():
    names = [name for name, _ in config.TIER_GETTERS]
    assert names[-3:] == ["OpenRouter Nemotron Ultra", "Kilo Dots 3 Note", "Ollama 7B"]
    assert names[-1] == "Ollama 7B"


def test_synthesis_only():
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]
    fast = [name for name, _ in config.FAST_TIERS]
    assert "Kilo Dots 3 Note" in synth
    assert "Kilo Dots 3 Note" not in cheap
    assert "Kilo Dots 3 Note" not in fast


def test_vision_text_only():
    from services.vision import vision_supported_tier

    assert vision_supported_tier("Kilo Dots 3 Note") is False
