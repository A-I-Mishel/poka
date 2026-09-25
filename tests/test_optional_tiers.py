"""Optional lanes: Cohere (no network).

Each lane is env-gated: a missing or placeholder key means the tier is
skipped (None), so unconfigured lanes never disturb the cascade.
Position: Gemini mains first, Groq strong fallback, then emergency pool
Cohere -> Nemotron Ultra (tail) -> local Ollama. Groq Fast / Mistral /
Free Router were removed Sep 2026 (superseded by the local cheap tier);
GLM 5.2 was removed Sep 2026 (failed trial); Qwen 3.8 27B and Ling 3.0
Flash VL were removed (trials ended / per user request).
Removed getters are gone and unknown names resolve to None.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

LANES = [
    # (tier name, key env, placeholder, model env, default model, base fragment)
    ("Cohere", "COHERE_API_KEY", "your_cohere_key_here",
     "COHERE_MODEL", config.COHERE_MODEL, "cohere.com"),
]

_GETTERS = {
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


def test_removed_lanes_resolve_to_none():
    """Groq Fast / Mistral / Free Router / TokenHarbor are gone: unknown names -> None."""
    assert config.get_tier_llm("Groq Fast", temperature=0.5) is None
    assert config.get_tier_llm("Mistral", temperature=0.5) is None
    assert config.get_tier_llm("OpenRouter Free Router", temperature=0.5) is None
    assert config.get_tier_llm("TokenHarbor Mimo", temperature=0.5) is None
    assert config.get_tier_llm("TokenHarbor DeepSeek", temperature=0.5) is None
    for stale in ("get_tier_groq_fast_llm", "get_tier_mistral_llm",
                  "get_tier_openrouter_free_router_llm",
                  "get_tier_tokenharbor_mimo_llm",
                  "get_tier_tokenharbor_deepseek_llm"):
        assert not hasattr(config, stale), stale


def test_cascade_position_gemini_led():
    names = [name for name, _ in config.TIER_GETTERS]
    assert names == [
        "Gemini 3.8 Flash", "Gemini 3.7 Flash", "Gemini 3.6 Flash",
        "Gemini 3.5 Flash", "Gemini 3.5 Flash Lite",
        "Gemini 3.1 Flash Lite", "Groq", "Cohere",
        "OpenRouter Nemotron Ultra", "Ollama 8B",
    ]


def test_registered_in_agent_table():
    from agent import providers

    names = [name for name, _ in providers.TIER_AGENT_GETTERS]
    for lane in ("Cohere", "Gemini 3.8 Flash", "Gemini 3.7 Flash",
                 "OpenRouter Nemotron Ultra"):
        assert lane in names
    for gone in ("Groq Fast", "Mistral", "OpenRouter Free Router",
                 "OpenRouter GLM 5.2", "OpenRouter Ling VL",
                 "TokenHarbor Mimo", "TokenHarbor DeepSeek"):
        assert gone not in names
