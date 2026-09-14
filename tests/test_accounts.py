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


def test_tokens_are_prefixed(client):
    body = _signup(client).json()
    assert body["token"].startswith("pluto_")


def test_legacy_unprefixed_tokens_still_verify(tmp_path, monkeypatch):
    import hashlib
    import json as _json

    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    handle, sess = _auth(username="legacy", password="s3cret-pw")
    from services import accounts as _accounts

    path = tmp_path / "data" / "accounts.json"
    reg = _json.loads(path.read_text(encoding="utf-8"))
    legacy = "legacy-token-without-prefix-123"
    digest = hashlib.sha256(legacy.encode()).hexdigest()
    reg["sessions"][digest] = {"user_id": sess["user_id"], "created": 9999999999.0}
    path.write_text(_json.dumps(reg), encoding="utf-8")
    assert _accounts.verify_session(legacy) == sess["user_id"]


def test_weak_passwords_rejected_on_signup(client):
    cases = [
        ("wu_common", "password1"),      # common password
        ("wu_same", "wu_same1!x"),       # contains the username
        ("wu_lower", "abcdefgh"),        # single class
        ("wu_upper", "ABCDEFGH"),        # single class
        ("wu_digit", "12345678"),        # single class + common
        ("wu_two", "abcd1234"),          # only two classes
    ]
    for username, weak in cases:
        res = client.post("/api/auth/signup",
                          json={"username": username, "password": weak})
        assert res.status_code == 400, (weak, res.text)
    # ...but a strong one works.
    assert client.post("/api/auth/signup",
                       json={"username": "strongone",
                             "password": "J7#mQ9!vzK2$x"}).status_code == 201


def test_lockout_after_repeated_failures(client):
    assert _signup(client, username="locky").status_code == 201
    codes = []
    for _ in range(5):
        res = client.post("/api/auth/login",
                          json={"username": "locky", "password": "wrong-pass"})
        codes.append(res.status_code)
    assert codes[:4] == [401] * 4
    assert codes[4] == 429
    assert "again in" in client.post(
        "/api/auth/login",
        json={"username": "locky", "password": "s3cret-pw"}).json()["detail"]


def test_change_password_rotates_and_revokes(client):
    first = _signup(client, username="rot").json()
    second = client.post("/api/auth/login",
                         json={"username": "rot", "password": "s3cret-pw"}).json()
    h1 = {"Authorization": "Bearer " + first["token"]}
    changed = client.post("/api/auth/change-password",
                          json={"current_password": "s3cret-pw",
                                "new_password": "N3w!Str0ng#pw"},
                          headers=h1)
    assert changed.status_code == 200, changed.text
    fresh = changed.json()["token"]
    assert fresh != first["token"] and fresh != second["token"]
    # Old sessions are dead, the new one lives.
    assert client.get("/api/auth/me", headers=h1).status_code == 401
    assert client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer " + second["token"]}).status_code == 401
    assert client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer " + fresh}).status_code == 200
    # Old password fails, new password works.
    assert client.post("/api/auth/login",
                       json={"username": "rot",
                             "password": "s3cret-pw"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"username": "rot",
                             "password": "N3w!Str0ng#pw"}).status_code == 200


def test_change_password_rejects_bad_current_and_weak(client):
    body = _signup(client, username="chg").json()
    headers = {"Authorization": "Bearer " + body["token"]}
    bad = client.post("/api/auth/change-password",
                      json={"current_password": "nope-nope",
                            "new_password": "N3w!Str0ng#pw"},
                      headers=headers)
    assert bad.status_code == 401
    weak = client.post("/api/auth/change-password",
                       json={"current_password": "s3cret-pw",
                             "new_password": "password1"},
                       headers=headers)
    assert weak.status_code == 400


def test_sessions_list_and_logout_all(client):
    first = _signup(client, username="sess").json()
    second = client.post("/api/auth/login",
                         json={"username": "sess",
                               "password": "s3cret-pw"}).json()
    h1 = {"Authorization": "Bearer " + first["token"]}
    listed = client.get("/api/auth/sessions", headers=h1)
    assert listed.status_code == 200, listed.text
    sessions = listed.json()["sessions"]
    assert len(sessions) == 2
    assert sum(1 for s in sessions if s["current"]) == 1
    assert all("created" in s for s in sessions)
    assert second["token"]  # both sessions exist
    out = client.post("/api/auth/logout-all", headers=h1)
    assert out.status_code == 200 and out.json()["revoked"] == 2
    assert client.get("/api/auth/me", headers=h1).status_code == 401


def test_account_endpoints_need_login(client):
    assert client.get("/api/auth/sessions").status_code == 401
    assert client.post("/api/auth/logout-all").status_code == 401
    assert client.post("/api/auth/change-password",
                       json={"current_password": "x",
                             "new_password": "N3w!Str0ng#pw"}).status_code == 401


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
    bob_chats = bob_c.get("/api/chats", headers=hb).json()
    assert bob_chats["chats"] == [] and bob_chats["current"] == []


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


def test_expired_session_rejected(tmp_path, monkeypatch):
    import time as _time

    from services import accounts as _accounts

    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    handle, sess = _auth(username="exp", password="s3cret-pw")
    assert _accounts.verify_session(sess["token"]) is not None
    # Backdate the session past the 30-day TTL.
    import hashlib as _hashlib
    import json as _json

    path = tmp_path / "data" / "accounts.json"
    reg = _json.loads(path.read_text(encoding="utf-8"))
    digest = _hashlib.sha256(sess["token"].encode()).hexdigest()
    reg["sessions"][digest]["created"] = _time.time() - 31 * 86400.0
    path.write_text(_json.dumps(reg), encoding="utf-8")
    assert _accounts.verify_session(sess["token"]) is None
