"""Fix 3 regression tests: kind-driven tier cooldowns.

Timeouts are congestion (first consecutive strike is a free pass, the
second cools briefly); quota errors cool for hours (daily resets make
10-minute re-probes pure waste); auth/invalid cool long; everything
else keeps the transient window. Success resets all streaks.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from agent.cascade import (
    _record_tier_failure,
    _record_tier_success,
    _tier_skipped,
    _usable_tiers,
    classify_provider_error,
)
from services.limits import (
    TIER_COOLDOWN_PERMANENT_SECONDS,
    TIER_COOLDOWN_QUOTA_SECONDS,
    TIER_COOLDOWN_TIMEOUT_SECONDS,
    TIER_COOLDOWN_TRANSIENT_SECONDS,
)


@pytest.fixture(autouse=True)
def _clean_cascade():
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()


def _remaining(name):
    return agent._TIER_SKIP_UNTIL.get(name, 0.0) - time.time()


def test_first_timeout_is_free_pass():
    _record_tier_failure("t", "timeout")
    assert not _tier_skipped("t")
    assert agent._TIER_TIMEOUTS.get("t") == 1


def test_second_consecutive_timeout_cools_briefly():
    _record_tier_failure("t", "timeout")
    _record_tier_failure("t", "timeout")
    assert _tier_skipped("t")
    assert _remaining("t") == pytest.approx(TIER_COOLDOWN_TIMEOUT_SECONDS, abs=5.0)
    assert _remaining("t") < TIER_COOLDOWN_TRANSIENT_SECONDS


def test_success_resets_timeout_streak():
    _record_tier_failure("t", "timeout")
    _record_tier_success("t")
    _record_tier_failure("t", "timeout")
    assert not _tier_skipped("t")
    assert agent._TIER_TIMEOUTS.get("t") == 1


def test_other_failure_resets_timeout_streak():
    _record_tier_failure("t", "timeout")
    assert agent._TIER_TIMEOUTS.get("t") == 1
    _record_tier_failure("t", "server")
    assert agent._TIER_TIMEOUTS == {}
    # The server failure itself still cools (transient window).
    assert _remaining("t") == pytest.approx(TIER_COOLDOWN_TRANSIENT_SECONDS, abs=5.0)


def test_quota_cools_for_hours_not_minutes():
    _record_tier_failure("t", "rate_limit")
    assert _tier_skipped("t")
    assert _remaining("t") == pytest.approx(TIER_COOLDOWN_QUOTA_SECONDS, abs=10.0)
    assert _remaining("t") > 3600.0


def test_auth_and_invalid_cool_long():
    _record_tier_failure("a", "auth")
    _record_tier_failure("b", "invalid")
    assert _remaining("a") == pytest.approx(TIER_COOLDOWN_PERMANENT_SECONDS, abs=5.0)
    assert _remaining("b") == pytest.approx(TIER_COOLDOWN_PERMANENT_SECONDS, abs=5.0)


def test_transient_kinds_keep_default_window():
    for name, kind in (("s", "server"), ("n", "network"), ("u", "unknown")):
        _record_tier_failure(name, kind)
        assert _remaining(name) == pytest.approx(TIER_COOLDOWN_TRANSIENT_SECONDS, abs=5.0)


def test_cooled_tier_leaves_usable_set():
    tiers = [("a", lambda: "A"), ("b", lambda: "B")]
    _record_tier_failure("a", "server")
    assert [n for n, _ in _usable_tiers(None, tiers)] == ["b"]
    _record_tier_success("a")
    assert [n for n, _ in _usable_tiers(None, tiers)] == ["a", "b"]


def test_classify_kinds_drive_cooldowns():
    assert classify_provider_error(TimeoutError("Model request timed out after 3s."))[0] == "timeout"
    assert classify_provider_error(Exception("429 quota exceeded"))[0] == "rate_limit"
    assert classify_provider_error(Exception("401 unauthorized"))[0] == "auth"
    assert classify_provider_error(Exception("500 internal error"))[0] == "server"
    assert classify_provider_error(Exception("400 bad request"))[0] == "invalid"
