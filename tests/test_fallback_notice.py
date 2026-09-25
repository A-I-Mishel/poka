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
    # Fallback tests post throwaway "hey": keep them on the model path.
    monkeypatch.setenv("PLUTO_GREETINGS", "0")
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
    assert _friendly_reason("capacity") == "capacity-limited"
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


def _client_with_corrections(monkeypatch, corrections):
    def _answer(user_input, history=None, **kwargs):
        return {
            "output": "hi",
            "active_tier": "Groq",
            "task_type": "creative",
            "tools_used": [],
            "sources": [],
            "request_id": "t",
            "corrections": corrections,
        }

    monkeypatch.setattr(agent, "answer_with_fallback", _answer)
    from backend.main import app

    return TestClient(app)


def test_send_reports_corrections(monkeypatch):
    with _client_with_corrections(monkeypatch, [["craeate", "create"]]) as client:
        res = client.post("/api/chat/send", json={"content": "craeate a repret"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["corrections"] == [["craeate", "create"]]
    assert body["message"]["corrections"] == [["craeate", "create"]]


def test_corrections_sanitized(monkeypatch):
    with _client_with_corrections(
        monkeypatch,
        [["ok", "ok"], ["a", "b"], "junk", ["x" * 100, "y"], ["p1", "q1"],
         ["p2", "q2"], ["p3", "q3"], ["p4", "q4"], ["p5", "q5"], ["p6", "q6"]],
    ) as client:
        res = client.post("/api/chat/send", json={"content": "hey"})
    assert res.status_code == 200, res.text
    body = res.json()
    got = body["message"]["corrections"]
    # identical pair + non-pair dropped, overlong capped at 32, max 5 kept
    assert ["ok", "ok"] not in got
    assert all(isinstance(p, list) and len(p) == 2 for p in got)
    assert all(len(s) <= 32 for p in got for s in p)
    assert len(got) <= 5


def test_no_corrections_key_when_absent(monkeypatch):
    with _client_with_stub(monkeypatch, "Groq") as client:
        res = client.post("/api/chat/send", json={"content": "hey"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["corrections"] == []
    assert "corrections" not in body["message"]
