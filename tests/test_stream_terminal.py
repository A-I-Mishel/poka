"""Stream terminal events: every outcome yields done or error.

A cancelled turn previously ended the SSE stream with no terminal
event, which the UI surfaced as the cryptic "Stream ended without a
result" with no retry context.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "stream-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    return tmp_path


@pytest.fixture()
def client(api_env):
    from backend.main import app

    with TestClient(app) as handle:
        yield handle


def test_cancelled_stream_yields_error_event(client, monkeypatch):
    import backend.routers.chat as chat_mod
    from agent.budget import TurnCancelled

    def _boom(*a, **k):
        raise TurnCancelled()

    monkeypatch.setattr(chat_mod, "run_chat", _boom)
    with client.stream("POST", "/api/chat/stream",
                       json={"content": "hello"}) as res:
        assert res.status_code == 200
        events = []
        for line in res.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    kinds = [e["type"] for e in events]
    assert "error" in kinds
    detail = next(e for e in events if e["type"] == "error")["detail"]
    assert "stopped before finishing" in detail
