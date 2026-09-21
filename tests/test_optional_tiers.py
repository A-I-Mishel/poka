"""Optional lanes: Mistral, Cohere, Groq Fast (no network).

Each lane is env-gated: a missing or placeholder key means the tier is
skipped (None), so unconfigured lanes never disturb the cascade.
Position: Gemini mains first, Groq strong fallback, Groq Fast cheap-only,
then emergency pool Cohere -> Free Router -> Mistral (last resort).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

LANES = [
    # (tier name, key env, placeholder, model env, default model, base fragment)
    ("Mistral", "MISTRAL_API_KEY", "your_mistral_key_here",
     "MISTRAL_MODEL", config.MISTRAL_MODEL, "mistral.ai"),
    ("Cohere", "COHERE_API_KEY", "your_cohere_key_here",
     "COHERE_MODEL", config.COHERE_MODEL, "cohere.com"),
]

_GETTERS = {
    "Mistral": config.get_tier_mistral_llm,
    "Cohere": config.get_tier_cohere_llm,
}


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture(params=LANES, ids=[lane[0] for lane in LANES])
def lane(request):
    keys = ("name", "key_env", "placeholder", "model_env", "default_model", "base")
    return dict(zip(keys, request.param, strict=True))


def _model_of(client):
    return getattr(client, "model_name", getattr(client, "model", None))


def test_no_key_means_skipped(monkeypatch, lane):
    monkeypatch.delenv(lane["key_env"], raising=False)
    assert _GETTERS[lane["name"]]() is None


def test_placeholder_key_is_skipped(monkeypatch, lane):
    monkeypatch.setenv(lane["key_env"], lane["placeholder"])
    assert _GETTERS[lane["name"]]() is None


def test_clients_built_with_key(monkeypatch, lane):
    monkeypatch.setenv(lane["key_env"], "test-key")
    # Hermetic against dev .env overrides.
    monkeypatch.delenv(lane["model_env"], raising=False)
    client = _GETTERS[lane["name"]]()
    assert client is not None
    assert _model_of(client) == lane["default_model"]
    base = getattr(client, "openai_api_base", "")
    assert lane["base"] in str(base)


def test_model_override(monkeypatch, lane):
    # Distinct key value so the (tier, temperature) cache entry is rebuilt.
    monkeypatch.setenv(lane["key_env"], "override-key")
    monkeypatch.setenv(lane["model_env"], "custom/model-1")
    assert _model_of(_GETTERS[lane["name"]]()) == "custom/model-1"


def test_clients_cached(monkeypatch, lane):
    monkeypatch.setenv(lane["key_env"], "test-key")
    assert _GETTERS[lane["name"]]() is _GETTERS[lane["name"]]()  # noqa: E501


def test_getter_by_name(monkeypatch, lane):
    monkeypatch.setenv(lane["key_env"], "test-key")
    assert config.get_tier_llm(lane["name"], temperature=0.5) is not None


def test_groq_fast_shares_groq_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert config.get_tier_groq_fast_llm() is None
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_FAST_MODEL", raising=False)
    client = config.get_tier_groq_fast_llm()
    assert client is not None
    assert _model_of(client) == config.GROQ_FAST_MODEL


def test_cascade_position_gemini_led():
    names = [name for name, _ in config.TIER_GETTERS]
    assert names == [
        "Gemini 3.8 Flash", "Gemini 3.7 Flash", "Gemini 3.6 Flash",
        "Gemini 3.5 Flash", "Groq", "Groq Fast", "Cohere",
        "OpenRouter Free Router", "Mistral",
    ]


def test_registered_in_agent_table():
    from agent import providers

    names = [name for name, _ in providers.TIER_AGENT_GETTERS]
    for lane in ("Mistral", "Cohere", "Groq Fast", "Gemini 3.8 Flash",
                 "Gemini 3.7 Flash"):
        assert lane in names
