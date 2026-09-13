"""Account tests: signup/login sessions isolate chats, memory, vaults.

Username/password accounts (services.accounts) yield stable
`acct-<hex>` ids, so every existing per-user store isolates with no
further changes. Session tokens travel as Bearer through the normal
auth chain (works in open and private modes); raw passwords and raw
session tokens are never persisted.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.auth import authenticate


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.delenv("PLUTO_ACCESS_TOKENS", raising=False)
    from services import ratelimit as rl

    old = rl.get_rate_limiter()
    rl.configure_rate_limiter(rl.MemoryRateLimiter())
    yield
    rl.configure_rate_limiter(old)


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


def _signup(client, username="alice", password="s3cret-pw"):
    return client.post("/api/auth/signup",
                       json={"username": username, "password": password})


def _auth(username="alice", password="s3cret-pw"):
    from backend.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as handle:
        res = handle.post("/api/auth/signup",
                          json={"username": username, "password": password})
        assert res.status_code == 201, res.text
        return handle, res.json()


def test_signup_opens_session(client):
    res = _signup(client)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["username"] == "alice"
    assert body["user_id"].startswith("acct-")
    assert len(body["token"]) > 20
    me = client.get("/api/auth/me",
                    headers={"Authorization": "Bearer " + body["token"]})
    assert me.status_code == 200, me.text
    assert me.json() == {"username": "alice", "user_id": body["user_id"],
                         "source": "account"}


def test_duplicate_username_rejected_case_insensitive(client):
    assert _signup(client).status_code == 201
    dup = _signup(client, username="Alice")
    assert dup.status_code == 409
    assert "taken" in dup.json()["detail"]


def test_bad_shapes_rejected(client):
    assert client.post("/api/auth/signup",
                       json={"username": "ab", "password": "s3cret-pw"}).status_code == 422
    assert client.post("/api/auth/signup",
                       json={"username": "bob!!", "password": "s3cret-pw"}).status_code in (400, 422)
    assert client.post("/api/auth/signup",
                       json={"username": "bob", "password": "short"}).status_code == 422


def test_login_roundtrip_and_failures(client):
    assert _signup(client).status_code == 201
    good = client.post("/api/auth/login",
                       json={"username": "alice", "password": "s3cret-pw"})
    assert good.status_code == 200, good.text
    assert good.json()["username"] == "alice"
    bad_pw = client.post("/api/auth/login",
                         json={"username": "alice", "password": "wrong-pass"})
    assert bad_pw.status_code == 401
    unknown = client.post("/api/auth/login",
                          json={"username": "ghost", "password": "wrong-pass"})
    assert unknown.status_code == 401
    # Failures never reveal which half was wrong.
    assert bad_pw.json()["detail"] == unknown.json()["detail"]


def test_authenticate_chain_prefers_session(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_ACCESS_TOKENS", "op-secret")
    handle, sess = _auth()
    result = authenticate(sess["token"])
    assert (result.identity.id, result.identity.source,
            result.method) == (sess["user_id"], "account", "session")
    assert result.authenticated is True


def test_accounts_isolate_memory_and_chats():
    alice_c, alice = _auth(username="alice")
    bob_c, bob = _auth(username="bob")
    assert alice["user_id"] != bob["user_id"]
    ha = {"Authorization": "Bearer " + alice["token"]}
    hb = {"Authorization": "Bearer " + bob["token"]}
    put = alice_c.put("/api/memory/notes", json={"text": "alice secret note"},
                      headers=ha)
    assert put.status_code == 200, put.text
    assert bob_c.get("/api/memory/notes", headers=hb).json()["text"] == ""
    assert alice_c.get("/api/memory/notes", headers=ha).json()["text"] == "alice secret note"
    assert alice_c.get("/api/chats", headers=ha).status_code == 200
    assert bob_c.get("/api/chats", headers=hb).json() == {"chats": [], "current": []}


def test_logout_revokes(client):
    body = _signup(client).json()
    headers = {"Authorization": "Bearer " + body["token"]}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    gone = client.get("/api/auth/me", headers=headers)
    assert gone.status_code == 401
    # Idempotent: logging out twice still returns ok.
    assert client.post("/api/auth/logout", headers=headers).status_code == 200


def test_private_mode_admits_session(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    handle, sess = _auth(username="priv")
    from backend.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as check:
        anon = check.get("/api/auth/me")
        assert anon.status_code == 401
        me = check.get("/api/auth/me",
                       headers={"Authorization": "Bearer " + sess["token"]})
        assert me.status_code == 200
        assert me.json()["username"] == "priv"


def test_secrets_never_persisted_in_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    handle, sess = _auth(username="alice", password="s3cret-pw")
    raw = (tmp_path / "data" / "accounts.json").read_text(encoding="utf-8")
    assert "s3cret-pw" not in raw
    assert sess["token"] not in raw
    stored = json.loads(raw)["users"]["alice"]
    assert set(stored) >= {"salt", "hash", "user_id", "username"}
    assert len(stored["salt"]) == 32 and len(stored["hash"]) == 64
