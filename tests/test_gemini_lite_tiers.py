"""Gemini Lite lanes: fresh per-model quota pools behind 3.5 Flash (no network).

Env-gated like the other Gemini lanes: a missing or placeholder
GEMINI_API_KEY means both tiers are skipped (None). Position: after
Gemini 3.5 Flash, before Groq, in both the full cascade and the
synthesis table; cheap- and vision-excluded so the fresh quota serves
final answers only.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


def _model_of(client):
    return getattr(client, "model", getattr(client, "model_name", None))


def test_no_key_means_skipped(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert config.get_tier_gemini35_lite_llm() is None
    assert config.get_tier_gemini31_lite_llm() is None


def test_placeholder_key_is_skipped(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_key_here")
    assert config.get_tier_gemini35_lite_llm() is None
    assert config.get_tier_gemini31_lite_llm() is None


def test_clients_built_with_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    # Hermetic against a dev .env that overrides the Lite model IDs.
    monkeypatch.delenv("GEMINI_35_LITE_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_31_LITE_MODEL", raising=False)
    # ChatGoogleGenerativeAI normalizes bare IDs to models/<id>.
    assert _model_of(config.get_tier_gemini35_lite_llm()) == "models/" + config.GEMINI_35_LITE_MODEL
    assert _model_of(config.get_tier_gemini31_lite_llm()) == "models/" + config.GEMINI_31_LITE_MODEL


def test_model_override(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "override-key")
    monkeypatch.setenv("GEMINI_35_LITE_MODEL", "gemini-3.5-flash-lite-override")
    assert _model_of(config.get_tier_gemini35_lite_llm()) == "models/gemini-3.5-flash-lite-override"


def test_getter_by_name(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert config.get_tier_llm("Gemini 3.5 Flash Lite", temperature=0.5) is not None
    assert config.get_tier_llm("Gemini 3.1 Flash Lite", temperature=0.5) is not None


def test_cascade_position():
    names = [name for name, _ in config.TIER_GETTERS]
    assert names.index("Gemini 3.5 Flash") < names.index("Gemini 3.5 Flash Lite")
    assert names.index("Gemini 3.5 Flash Lite") < names.index("Gemini 3.1 Flash Lite")
    assert names.index("Gemini 3.1 Flash Lite") < names.index("Groq")


def test_synthesis_member_cheap_excluded():
    synth = [name for name, _ in config.SYNTHESIS_TIERS]
    cheap = [name for name, _ in config.CHEAP_TIERS]
    assert "Gemini 3.5 Flash Lite" in synth
    assert "Gemini 3.1 Flash Lite" in synth
    assert "Gemini 3.5 Flash Lite" not in cheap
    assert "Gemini 3.1 Flash Lite" not in cheap


def test_registered_in_agent_table():
    from agent import providers

    names = [name for name, _ in providers.TIER_AGENT_GETTERS]
    assert "Gemini 3.5 Flash Lite" in names
    assert "Gemini 3.1 Flash Lite" in names
