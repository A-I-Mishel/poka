"""Approval-token tests: staging, single-use consume, expiry, router flow.

Model-supplied confirmation is forgeable, so destructive tools run only
with server-minted single-use tokens approved through the UI.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import approvals as approvals_svc


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)


def test_request_dedupes_identical_action():
    first_id, _t1, created1 = approvals_svc.request_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, "run it")
    second_id, _t2, created2 = approvals_svc.request_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, "run it")
    assert created1 is True and created2 is False
    assert first_id == second_id


def test_consume_single_use():
    approval_id, token, _ = approvals_svc.request_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, "run it")
    ok, stored = approvals_svc.consume_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, token)
    assert ok is True and stored == {"sql": "DELETE FROM t"}
    # Second use fails even with the same token.
    ok2, detail = approvals_svc.consume_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, token)
    assert ok2 is False
    assert detail in ("unknown", "used")
    assert approval_id


def test_consume_rejects_wrong_token_and_args():
    _id, token, _ = approvals_svc.request_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, "run it")
    ok, _ = approvals_svc.consume_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, "forged-token")
    assert ok is False
    # Right token, different action: no cross-action replay.
    ok, detail = approvals_svc.consume_approval(
        "u1", "execute_sql", {"sql": "DROP TABLE t"}, token)
    assert ok is False and detail == "mismatch"


def test_users_isolated():
    _id, token, _ = approvals_svc.request_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, "run it")
    ok, _ = approvals_svc.consume_approval(
        "u2", "execute_sql", {"sql": "DELETE FROM t"}, token)
    assert ok is False


def test_expiry(monkeypatch):
    monkeypatch.setattr(approvals_svc, "APPROVAL_TTL_SECONDS", -1)
    _id, token, _ = approvals_svc.request_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, "run it")
    ok, detail = approvals_svc.consume_approval(
        "u1", "execute_sql", {"sql": "DELETE FROM t"}, token)
    assert ok is False and detail == "expired"


def test_list_hides_tokens_until_rotated():
    approvals_svc.request_approval("u1", "execute_sql", {"sql": "x"}, "run it")
    plain = approvals_svc.list_pending("u1")
    assert len(plain) == 1 and "token" not in plain[0]
    rotated = approvals_svc.list_pending("u1", rotate_tokens=True)
    assert "token" in rotated[0] and rotated[0]["id"] == plain[0]["id"]


def test_reject_discards():
    approval_id, _t, _ = approvals_svc.request_approval(
        "u1", "execute_sql", {"sql": "x"}, "run it")
    assert approvals_svc.reject_approval("u1", approval_id) is True
    assert approvals_svc.reject_approval("u1", approval_id) is False
    assert approvals_svc.list_pending("u1") == []


def test_pending_since_filters():
    approvals_svc.request_approval("u1", "execute_sql", {"sql": "x"}, "run it")
    assert len(approvals_svc.pending_since("u1", 0)) == 1
    assert approvals_svc.pending_since("u1", 9999999999.0) == []


def test_fallback_parsers_skip_mutating_tools():
    from agent.toolrun import _fallback_tool_calls_from_text

    leaked = '{"tool": "execute_sql", "sql": "DROP TABLE t"}'
    assert _fallback_tool_calls_from_text(leaked) == []
    assert _fallback_tool_calls_from_text('[Tool call: delete_calendar_event(event_id="x")]') == []
    ok = _fallback_tool_calls_from_text('{"tool": "read_document", "upload_id": "ab12"}')
    assert [c["name"] for c in ok] == ["read_document"]


def _approve_client(client):
    body = client.get("/api/approvals").json()
    assert len(body["approvals"]) == 1
    item = body["approvals"][0]
    assert "token" in item and item["token"]
    return item


def test_router_approve_executes_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_USER_ID", "router-user")
    from fastapi.testclient import TestClient

    from backend.main import app
    from services import context as ctx
    from tools.database_tool import execute_sql

    ctx.set_current_user_id("router-user")
    ctx.set_limit_key("router-user")
    try:
        out = execute_sql.invoke({"sql": "CREATE TABLE t (a TEXT)"})
        assert "approval_id=" in out
        with TestClient(app) as client:
            item = _approve_client(client)
            first = client.post(
                f"/api/approvals/{item['id']}/approve",
                json={"token": item["token"]})
            assert first.status_code == 200, first.text
            assert first.json()["result"].startswith("STATUS=OK")
            # Double-click spends nothing twice.
            again = client.post(
                f"/api/approvals/{item['id']}/approve",
                json={"token": item["token"]})
            assert again.status_code == 410
            assert client.get("/api/approvals").json() == {"approvals": []}
    finally:
        ctx.set_current_user_id(None)
        ctx.set_limit_key(None)


def test_router_reject_discards(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_USER_ID", "router-user")
    from fastapi.testclient import TestClient

    from backend.main import app
    from services import context as ctx
    from tools.database_tool import execute_sql

    ctx.set_current_user_id("router-user")
    ctx.set_limit_key("router-user")
    try:
        out = execute_sql.invoke({"sql": "CREATE TABLE t (a TEXT)"})
        assert "approval_id=" in out
        approval_id = out.split("approval_id=")[1].split(")")[0]
        with TestClient(app) as client:
            res = client.post(f"/api/approvals/{approval_id}/reject")
            assert res.status_code == 200
            assert client.get("/api/approvals").json() == {"approvals": []}
    finally:
        ctx.set_current_user_id(None)
        ctx.set_limit_key(None)
