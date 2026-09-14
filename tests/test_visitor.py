"""Visitor persistence tests: logged-out browsers keep one vault.

Without a credential, open mode used to mint a fresh random id per
request, so a chat saved by POST /api/chat/* was unreadable by the
next GET /api/chats and the conversation vanished after every reply.
A well-formed X-Pluto-Visitor header now pins the browser to one
vault; malformed headers fall back to per-request ids, and private
mode ignores the header entirely.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.deps import _visitor_id


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.delenv("PLUTO_ACCESS_TOKENS", raising=False)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.delenv("PLUTO_ACCESS_TOKENS", raising=False)
    from backend.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as handle:
        yield handle


def test_visitor_id_shapes():
    from backend.deps import visitor_vault_id
    assert _visitor_id("a1b2c3d4e5f60718293a4b5c6d7e8f90") is not None
    assert _visitor_id("  a1b2c3d4  ") == "a1b2c3d4"
    assert _visitor_id("") is None
    assert _visitor_id(None) is None
    assert _visitor_id("short") is None
    assert _visitor_id("x" * 57) is None
    assert _visitor_id("../escape") is None
    assert _visitor_id("a/b") is None
    assert _visitor_id("semi;colon") is None
    # Namespacing prevents squatting on stable vault ids.
    assert visitor_vault_id("browser111") == "visitor-browser111"
    assert not visitor_vault_id("acct-abc123").startswith("acct-")


def test_visitor_cannot_squat_account_vault(client):
    # Even when the raw header equals an account-style id, the vault
    # id is namespaced away from it.
    from backend.deps import visitor_vault_id
    assert visitor_vault_id("acct-abc123") != "acct-abc123"


def test_same_visitor_shares_vault(client):
    headers = {"X-Pluto-Visitor": "browser111222333444"}
    put = client.put("/api/memory/notes", json={"text": "visitor note"},
                     headers=headers)
    assert put.status_code == 200, put.text
    again = client.get("/api/memory/notes", headers=headers)
    assert again.status_code == 200, again.text
    assert again.json() == {"text": "visitor note"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.json()["user_id"] == "visitor-browser111222333444"
    assert me.json()["source"] == "ephemeral"


def test_different_visitors_isolated(client):
    client.put("/api/memory/notes", json={"text": "aaa"},
               headers={"X-Pluto-Visitor": "browseraaaaaaaa1111"})
    other = client.get("/api/memory/notes",
                       headers={"X-Pluto-Visitor": "browserbbbbbbbb2222"})
    assert other.json() == {"text": ""}


def test_malformed_visitor_falls_back_to_ephemeral(client):
    put = client.put("/api/memory/notes", json={"text": "lost note"},
                     headers={"X-Pluto-Visitor": "../nope"})
    assert put.status_code == 200, put.text
    # Random id per request: the write is unreadable afterwards, but
    # nothing errors and no traversal happened on disk.
    again = client.get("/api/memory/notes",
                       headers={"X-Pluto-Visitor": "../nope"})
    assert again.json() == {"text": ""}


def test_visitor_ignored_when_token_present(client, monkeypatch):
    monkeypatch.setenv("PLUTO_ACCESS_TOKENS", "op-secret")
    me = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer op-secret",
                 "X-Pluto-Visitor": "browser111222333444"},
    )
    assert me.status_code == 200
    assert me.json()["source"] == "token"
    assert me.json()["username"] is None


def test_private_mode_ignores_visitor(client, monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    res = client.get("/api/memory/notes",
                     headers={"X-Pluto-Visitor": "browser111222333444"})
    assert res.status_code == 401
