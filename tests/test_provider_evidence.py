"""Provider-evidence classification: 429 vs 503 by returned evidence.

A bare service-unavailable/capacity 503 must not inherit the 6-hour
quota ban; genuine quota evidence (status, reasons, quota language,
provider delays) must still take the quota path. Shapes mirror
recorded Google API error payloads (status + JSON body); auth/invalid
handling is unchanged.
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import cascade as _cascade
from agent.cascade import (
    _record_tier_failure,
    _tier_skipped,
    classify_provider_error,
)
from services.limits import (
    TIER_COOLDOWN_CAPACITY_SECONDS,
    TIER_COOLDOWN_QUOTA_SECONDS,
    TIER_COOLDOWN_TRANSIENT_SECONDS,
)


@pytest.fixture(autouse=True)
def _clean_cascade():
    for store in (_cascade._TIER_FAILS, _cascade._TIER_SKIP_UNTIL,
                  _cascade._TIER_TIMEOUTS, _cascade._TIER_LAST_ERROR):
        store.clear()
    yield
    for store in (_cascade._TIER_FAILS, _cascade._TIER_SKIP_UNTIL,
                  _cascade._TIER_TIMEOUTS, _cascade._TIER_LAST_ERROR):
        store.clear()


def _remaining(name):
    return _cascade._TIER_SKIP_UNTIL.get(name, 0.0) - time.time()


class _GoogleError(Exception):
    """Recorded-shape provider failure: status + headers + JSON body."""

    def __init__(self, message="", status_code=None, headers=None, body=None):
        payload = str(message or "")
        if body is not None:
            encoded = json.dumps(body)
            payload = f"{payload} {encoded}".strip()

        super().__init__(payload)
        if status_code is not None:
            self.status_code = status_code
        if headers is not None:
            self.response = type("Resp", (), {"headers": dict(headers),
                                              "status_code": status_code})()


def _google_429_body(reason="RATE_LIMIT_EXHAUSTED", retry_delay="49s"):
    return {"error": {
        "code": 429,
        "message": "Quota exceeded for metric.",
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.ErrorInfo",
             "reason": reason},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo",
             "retryDelay": retry_delay},
        ],
    }}


def _google_503_body(reason="SERVICE_UNAVAILABLE"):
    return {"error": {
        "code": 503,
        "message": "The service is currently unavailable.",
        "status": "UNAVAILABLE",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.ErrorInfo",
             "reason": reason},
        ],
    }}


def test_genuine_429_body_takes_quota_path_with_delay():
    err = _GoogleError(status_code=429, body=_google_429_body())
    assert classify_provider_error(err)[0] == "rate_limit"
    _record_tier_failure("g", "rate_limit", err)
    assert _remaining("g") == pytest.approx(49.0, abs=5.0)
    assert _remaining("g") < TIER_COOLDOWN_QUOTA_SECONDS


def test_quota_reason_in_503_body_stays_quota():
    # A 503 quoting quota is quota exhaustion, not an outage.
    body = _google_503_body()
    body["error"]["message"] = "Quota exceeded for metric, try later."
    err = _GoogleError(status_code=503, body=body)
    assert classify_provider_error(err)[0] == "rate_limit"
    _record_tier_failure("g", "rate_limit", err)
    assert _remaining("g") == pytest.approx(TIER_COOLDOWN_QUOTA_SECONDS, abs=10.0)


def test_bare_503_takes_capacity_path():
    err = _GoogleError(status_code=503, body=_google_503_body())
    assert classify_provider_error(err)[0] == "capacity"
    _record_tier_failure("g", "capacity", err)
    assert _tier_skipped("g")
    assert _remaining("g") == pytest.approx(TIER_COOLDOWN_CAPACITY_SECONDS, abs=10.0)
    assert _remaining("g") > TIER_COOLDOWN_TRANSIENT_SECONDS
    assert _remaining("g") < TIER_COOLDOWN_QUOTA_SECONDS


def test_bare_503_status_only_takes_capacity_path():
    err = _GoogleError(status_code=503)
    assert classify_provider_error(err)[0] == "capacity"


def test_overloaded_without_quota_is_capacity_not_quota():
    # Demoted from the old blanket rate_limit: overload alone proves
    # congestion, never daily-quota exhaustion.
    err = _GoogleError("The model is overloaded, try again later.")
    assert classify_provider_error(err)[0] == "capacity"


def test_overloaded_with_quota_language_stays_quota():
    err = _GoogleError("Overloaded: quota exceeded for free tier requests.")
    assert classify_provider_error(err)[0] == "rate_limit"


def test_capacity_honors_retry_after_header():
    err = _GoogleError(status_code=503,
                       headers={"Retry-After": "120"},
                       body=_google_503_body())
    assert classify_provider_error(err)[0] == "capacity"
    _record_tier_failure("g", "capacity", err)
    assert _remaining("g") == pytest.approx(120.0, abs=5.0)
    assert _remaining("g") < TIER_COOLDOWN_CAPACITY_SECONDS


def test_capacity_ignores_oversized_delay():
    err = _GoogleError(status_code=503,
                       headers={"Retry-After": "999999"},
                       body=_google_503_body())
    _record_tier_failure("g", "capacity", err)
    assert _remaining("g") == pytest.approx(TIER_COOLDOWN_CAPACITY_SECONDS, abs=10.0)


def test_retry_delay_body_parsed_without_header():
    err = _GoogleError(body=_google_429_body(retry_delay="90s"))
    assert classify_provider_error(err)[0] == "rate_limit"
    _record_tier_failure("g", "rate_limit", err)
    assert _remaining("g") == pytest.approx(90.0, abs=5.0)


def test_unchanged_kinds():
    assert classify_provider_error(_GoogleError(status_code=500))[0] == "server"
    assert classify_provider_error(_GoogleError(status_code=502))[0] == "server"
    assert classify_provider_error(_GoogleError(status_code=401))[0] == "auth"
    assert classify_provider_error(_GoogleError(status_code=400))[0] == "invalid"
    assert classify_provider_error(TimeoutError("timed out after 3s."))[0] == "timeout"
    assert classify_provider_error(Exception("connection reset by peer"))[0] == "network"
    assert classify_provider_error(Exception("some mystery failure"))[0] == "unknown"
    # Encrypted-reasoning precedence over 400 preserved.
    assert classify_provider_error(
        Exception("400 reasoning 'encrypted_content' was not issued to this caller")
    )[0] == "unknown"
