"""Tier fail-fast: SDK retries disabled on every tier (Phase 1 addendum).

Live finding: langchain tenacity retries (2s/4s/8s... backoff) fire
INSIDE one cascade attempt — each retry burns free-tier quota (daily
allowance ~20) and adds minutes before failover. The cascade is the
retry mechanism (across tiers, with cooldowns), so clients run with
max_retries=0 and fail fast into it.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_mod


def _fresh_client(getter, env_key):
    config_mod._clear_client_cache()
    return getter()


def test_gemini_tiers_fail_fast(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-failfast")
    try:
        assert _fresh_client(config_mod.get_tier_gemini38_llm, "x").max_retries == 0
        assert _fresh_client(config_mod.get_tier_gemini37_llm, "x").max_retries == 0
        assert _fresh_client(config_mod.get_tier2_llm, "x").max_retries == 0
        assert _fresh_client(config_mod.get_tier3_llm, "x").max_retries == 0
    finally:
        config_mod._clear_client_cache()


def test_openai_compatible_tiers_fail_fast(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-failfast")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-failfast")
    try:
        assert _fresh_client(config_mod.get_tier_groq_llm, "x").max_retries == 0
        assert _fresh_client(
            config_mod.get_tier_openrouter_ultra_llm, "x").max_retries == 0
    finally:
        config_mod._clear_client_cache()
