"""Fix 6 regression tests: authenticate() is the single source of truth.

services.auth.authenticate() owns the whole chain (token -> mode chain)
and backend.deps delegates to it instead of reimplementing Bearer
handling. Private-mode semantics exist in exactly one place.
"""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from services.auth import AuthResult, authenticate
from services.identity import AuthRequired, UserIdentity


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def open_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.delenv("PLUTO_ACCESS_TOKENS", raising=False)
    return tmp_path


def _token_id(secret):
    return "token-" + hashlib.sha256(secret.encode()).hexdigest()[:32]


def test_open_ephemeral(open_env):
    result = authenticate()
    assert result.identity.source == "ephemeral"
    assert result.authenticated is False
    assert result.method == "ephemeral"


def test_open_env_identity(open_env, monkeypatch):
    monkeypatch.setenv("PLUTO_USER_ID", "op-user")
    result = authenticate()
    assert (result.identity.id, result.identity.source) == ("op-user", "env")
    assert result.authenticated is True


def test_token_beats_env(open_env, monkeypatch):
    monkeypatch.setenv("PLUTO_USER_ID", "op-user")
    monkeypatch.setenv("PLUTO_ACCESS_TOKENS", "alpha-secret")
    result = authenticate("alpha-secret")
    assert result.identity.id == _token_id("alpha-secret")
    assert result.identity.source == "token"
    assert result.authenticated is True


def test_token_is_stable(open_env, monkeypatch):
    monkeypatch.setenv("PLUTO_ACCESS_TOKENS", "alpha-secret, beta-secret")
    assert authenticate("beta-secret").identity.id == _token_id("beta-secret")
    assert authenticate("beta-secret").identity.id == authenticate("beta-secret").identity.id


def test_bad_token_rejected(open_env, monkeypatch):
    monkeypatch.setenv("PLUTO_ACCESS_TOKENS", "alpha-secret")
    with pytest.raises(AuthRequired, match="Invalid access token."):
        authenticate("wrong-secret")


def test_bad_token_with_none_configured(open_env):
    with pytest.raises(AuthRequired, match="Invalid access token."):
        authenticate("anything")


def test_private_env_identity(open_env, monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    monkeypatch.setenv("PLUTO_USER_ID", "boss")
    result = authenticate()
    assert (result.identity.id, result.identity.source) == ("boss", "env")


def test_private_token_admitted(open_env, monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    monkeypatch.setenv("PLUTO_ACCESS_TOKENS", "alpha-secret")
    result = authenticate("alpha-secret")
    assert result.identity.source == "token"


def test_private_no_credential_rejected(open_env, monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    with pytest.raises(AuthRequired, match="Authentication required."):
        authenticate()


def test_deps_delegates_to_authenticate(open_env, monkeypatch):
    import backend.deps as deps

    calls = []

    def _fake_authenticate(presented=None):
        calls.append(presented)
        return AuthResult(
            identity=UserIdentity(id="delegated", email=None, source="env"),
            authenticated=True,
            method="env",
        )

    monkeypatch.setattr(deps, "authenticate", _fake_authenticate)
    from backend.main import app

    with TestClient(app) as client:
        res = client.get("/api/health", headers={"Authorization": "Bearer whatever"})
        assert res.status_code == 200
    # The raw header value reached the single chain (Bearer parsed in deps).
    assert calls == ["whatever"]


def test_private_mode_endpoints(open_env, monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    monkeypatch.setenv("PLUTO_ACCESS_TOKENS", "s3cret")
    from backend.main import app

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 401
        bad = client.get("/api/health", headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401
        assert bad.json()["detail"] == "Invalid access token."
        good = client.get("/api/health", headers={"Authorization": "Bearer s3cret"})
        assert good.status_code == 200
        assert good.json()["auth_mode"] == "private"
