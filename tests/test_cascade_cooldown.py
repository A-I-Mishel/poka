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
    NO_TOOLS_TIERS,
    _friendly_reason,
    _record_tier_failure,
    _record_tier_success,
    _tier_skipped,
    _usable_tiers,
    classify_provider_error,
    last_tier_error,
)
from services.limits import (
    TIER_COOLDOWN_CAPACITY_SECONDS,
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


def test_capacity_cools_for_minutes_not_hours():
    _record_tier_failure("c", "capacity")
    assert _tier_skipped("c")
    assert _remaining("c") == pytest.approx(TIER_COOLDOWN_CAPACITY_SECONDS, abs=10.0)
    assert _remaining("c") > TIER_COOLDOWN_TRANSIENT_SECONDS
    assert _remaining("c") < TIER_COOLDOWN_QUOTA_SECONDS


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


class _HttpError(Exception):
    def __init__(self, message="boom", status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        if retry_after is not None:

            class _Resp:
                headers = {"Retry-After": str(retry_after)}

            self.response = _Resp()


def test_classify_uses_status_code_attribute():
    # No substring to match — solely the 429 status.
    assert classify_provider_error(_HttpError(status_code=429))[0] == "rate_limit"
    assert classify_provider_error(_HttpError(status_code=401))[0] == "auth"
    assert classify_provider_error(_HttpError(status_code=503))[0] == "capacity"
    assert classify_provider_error(_HttpError(status_code=408))[0] == "timeout"


def test_classify_usage_limit_phrases():
    assert classify_provider_error(Exception("daily usage limit reached for model"))[0] == "rate_limit"
    assert classify_provider_error(Exception("usagelimit: exceeded budget"))[0] == "rate_limit"


def test_classify_no_tools_capability():
    # Screenshot regression: qwen2.5vl:3b 400s any tools-bound call.
    # Must precede the 400/invalid branch (gateways report HTTP 400).
    err = Exception("Error code: 400 - {'message': "
                    "'registry.ollama.ai/library/qwen2.5vl:3b "
                    "does not support tools'}")
    kind, retryable = classify_provider_error(err)
    assert kind == "capability"
    assert retryable is True
    assert _friendly_reason(kind) == "does not support tools"
    assert "Ollama VL 3B" in NO_TOOLS_TIERS


def test_capability_never_cools_and_stays_explained():
    err = Exception("does not support tools")
    _record_tier_failure("vl", "capability", err)
    _record_tier_failure("vl", "capability", err)
    assert _tier_skipped("vl") is False
    assert agent._TIER_FAILS.get("vl") is None
    kind, _detail = last_tier_error("vl")
    assert kind == "capability"


def test_rate_limit_honors_retry_after():
    err = _HttpError(status_code=429, retry_after=60)
    assert classify_provider_error(err)[0] == "rate_limit"
    _record_tier_failure("r", "rate_limit", err)
    assert _remaining("r") == pytest.approx(60.0, abs=5.0)
    assert _remaining("r") < TIER_COOLDOWN_QUOTA_SECONDS


def test_rate_limit_ignores_large_retry_after():
    err = _HttpError(status_code=429, retry_after=999999)
    _record_tier_failure("r", "rate_limit", err)
    assert _remaining("r") == pytest.approx(TIER_COOLDOWN_QUOTA_SECONDS, abs=10.0)


def test_threaded_failure_accounting_is_exact():
    # Real race the lock prevents: many workers incrementing the same
    # tier's timeout streak must end with the exact sum.
    import threading
    import agent as agent_mod

    workers = 8
    iters = 100

    def hammer():
        for _ in range(iters):
            _record_tier_failure("th", "timeout")

    threads = [threading.Thread(target=hammer) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert agent_mod._TIER_TIMEOUTS.get("th") == workers * iters
    # Clean slate for the fixture teardown.
    agent_mod._TIER_TIMEOUTS.pop("th", None)
