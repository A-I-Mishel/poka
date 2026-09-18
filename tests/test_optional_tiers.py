"""Optional free-tier lanes: GitHub Models, Mistral, NVIDIA (no network).

Each lane is env-gated: a missing or placeholder key means the tier is
skipped (None), so unconfigured lanes never disturb the cascade.
Position: GitHub Models + NVIDIA are direct providers after Gemini 3.5
Flash, before the OpenRouter aggregator block (direct providers first,
aggregator fallbacks last); Mistral is the last-resort tier at the very
bottom of the cascade.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

LANES = [
    # (tier name, key env, placeholder, model env, default model, base fragment)
    ("GitHub Models", "GITHUB_MODELS_TOKEN", "your_github_models_token_here",
     "GITHUB_MODELS_MODEL", config.GITHUB_MODELS_MODEL, "models.github.ai"),
    ("Mistral", "MISTRAL_API_KEY", "your_mistral_key_here",
     "MISTRAL_MODEL", config.MISTRAL_MODEL, "mistral.ai"),
    ("NVIDIA", "NVIDIA_API_KEY", "your_nvidia_key_here",
     "NVIDIA_MODEL", config.NVIDIA_MODEL, "nvidia.com"),
]

_GETTERS = {
    "GitHub Models": config.get_tier_github_models_llm,
    "Mistral": config.get_tier_mistral_llm,
    "NVIDIA": config.get_tier_nvidia_llm,
}


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture(params=LANES, ids=[lane[0] for lane in LANES])
def lane(request):
    keys = ("name", "key_env", "placeholder", "model_env", "default_model", "base")
    return dict(zip(keys, request.param))


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


def test_cascade_position_after_gemini_before_openrouter():
    names = [name for name, _ in config.TIER_GETTERS]
    assert names.index("Gemini 3.5 Flash") < names.index("GitHub Models")
    assert names.index("GitHub Models") < names.index("NVIDIA")
    assert names.index("NVIDIA") < names.index("OpenRouter Nemotron Ultra")
    # Mistral is last resort: after every OpenRouter fallback.
    assert names.index("OpenRouter Free Router") < names.index("Mistral")
    assert names[-1] == "Mistral"


def test_registered_in_agent_table():
    from agent import providers

    names = [name for name, _ in providers.TIER_AGENT_GETTERS]
    for lane in ("GitHub Models", "Mistral", "NVIDIA"):
        assert lane in names
