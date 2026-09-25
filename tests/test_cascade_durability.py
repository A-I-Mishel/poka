"""Cascade durability: cooldowns survive restarts, calls counted daily.

A restart must not re-walk dead lanes (each re-walk burns quota
re-learning a 429), and /api/ops/tiers must show per-tier calls-today
so quota math is visible instead of guessed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent.cascade as cascade_mod
from agent.cascade import (
    _calls_today,
    _run_cascade_step,
    _tier_skipped,
    tier_status_snapshot,
)


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path))
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
    cascade_mod._TIER_CALLS_TODAY.clear()
    cascade_mod._TIER_CALLS_DATE = ""
    monkeypatch.setattr(cascade_mod, "_STATE_LOADED", False)
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
    cascade_mod._TIER_CALLS_TODAY.clear()
    cascade_mod._TIER_CALLS_DATE = ""
    monkeypatch.setattr(cascade_mod, "_STATE_LOADED", False)


def _record_quota(name):
    from agent.cascade import _record_tier_failure

    _record_tier_failure(name, "rate_limit", Exception("429 quota exhausted"))


def test_cooldown_survives_restart():
    _record_quota("Gemini 3.8 Flash")
    assert _tier_skipped("Gemini 3.8 Flash") is True
    # Simulate a restart: drop all memory, keep only the file.
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    cascade_mod._STATE_LOADED = False
    assert _tier_skipped("Gemini 3.8 Flash") is True


def test_reset_clears_persisted_skip(tmp_path, monkeypatch):
    from agent.cascade import reset_tier_state

    _record_quota("Groq")
    assert _tier_skipped("Groq") is True
    assert reset_tier_state("Groq") >= 1
    agent._TIER_SKIP_UNTIL.clear()
    monkeypatch.setattr(cascade_mod, "_STATE_LOADED", False)
    assert _tier_skipped("Groq") is False


def test_calls_counted_per_tier_per_day():
    def _ok(name, llm):
        return "done"

    tiers = [("t1", lambda: object()), ("t2", lambda: object())]
    tier, out = _run_cascade_step(_ok, tiers=tiers)
    assert (tier, out) == ("t1", "done")
    assert _calls_today("t1") == 1
    assert _calls_today("t2") == 0


def test_calls_reset_on_date_rollover(monkeypatch):
    def _ok(name, llm):
        return "done"

    _run_cascade_step(_ok, tiers=[("t1", lambda: object())])
    assert _calls_today("t1") == 1
    monkeypatch.setattr(cascade_mod, "_today_key", lambda: "2999-01-02")
    assert _calls_today("t1") == 0


def test_snapshot_carries_calls_today():
    def _ok(name, llm):
        return "done"

    tiers = [("t1", lambda: object())]
    _run_cascade_step(_ok, tiers=tiers)
    snap = {e["name"]: e for e in tier_status_snapshot(tiers=tiers)}
    assert snap["t1"]["calls_today"] == 1


def test_unwritable_state_dir_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setenv("PLUTO_DATA_DIR", str(blocker))
    monkeypatch.setattr(cascade_mod, "_STATE_LOADED", False)
    _record_quota("t9")
    assert _tier_skipped("t9") is True
