"""Fallback notice: preferred-vs-actual tier plus reason, for every model.

When the answering tier differs from the requested preference, the
response (and the stored message meta) names the requested tier and
the classified reason (rate-limited, timed out, ...) so the UI can
say why instead of silently showing the preference.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from agent.cascade import (
    _friendly_reason,
    _record_tier_failure,
    _TIER_FAILS,
    _TIER_LAST_ERROR,
    _TIER_SKIP_UNTIL,
    _TIER_TIMEOUTS,
    last_tier_error,
)
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "fb-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    for store in (_TIER_FAILS, _TIER_LAST_ERROR, _TIER_SKIP_UNTIL, _TIER_TIMEOUTS):
        store.clear()
    agent._clear_summary_cache()
    yield
    for store in (_TIER_FAILS, _TIER_LAST_ERROR, _TIER_SKIP_UNTIL, _TIER_TIMEOUTS):
        store.clear()


def test_failure_kind_maps_to_reason():
    assert _friendly_reason("rate_limit") == "rate-limited"
    assert _friendly_reason("timeout") == "timed out"
    assert _friendly_reason("auth") == "unavailable (auth)"
    assert _friendly_reason("bogus-kind") == "temporarily unavailable"


def test_last_error_recorded():
    _record_tier_failure("Big Pickle", "rate_limit", RuntimeError("429 slow down"))
    kind, detail = last_tier_error("Big Pickle")
    assert kind == "rate_limit"
    assert "429" in detail
    assert last_tier_error("Unknown Tier") is None
    assert last_tier_error("") is None


def _client_with_stub(monkeypatch, actual):
    def _answer(user_input, history=None, **kwargs):
        return {
            "output": "hi",
            "active_tier": actual,
            "task_type": "simple",
            "tools_used": [],
            "sources": [],
            "request_id": "t",
        }

    monkeypatch.setattr(agent, "answer_with_fallback", _answer)
    from backend.main import app

    return TestClient(app)


def test_send_reports_fallback_with_reason(monkeypatch):
    _record_tier_failure("Big Pickle", "rate_limit", RuntimeError("429 slow down"))
    with _client_with_stub(monkeypatch, "Groq") as client:
        res = client.post(
            "/api/chat/send", json={"content": "hey", "active_tier": "Big Pickle"}
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["active_tier"] == "Groq"
    assert body["fallback"] == {"requested": "Big Pickle", "reason": "rate-limited"}
    assert body["message"]["model"] == "Groq"
    assert body["message"]["fallback"] == {
        "requested": "Big Pickle",
        "reason": "rate-limited",
    }


def test_no_fallback_when_preferred_answers(monkeypatch):
    with _client_with_stub(monkeypatch, "Big Pickle") as client:
        res = client.post(
            "/api/chat/send", json={"content": "hey", "active_tier": "Big Pickle"}
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fallback"] is None
    assert "fallback" not in body["message"]
