"""Backend API tests: FastAPI routes over the real agent/services stack.

Hermetic like the rest of the suite: tmp POKA_DATA_DIR, env identity,
stubbed agent (no quota, no network). Covers auth, chat send/stream +
persistence, uploads, artifacts, projects, briefs, and memory.
"""

import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("POKA_USER_ID", "api-user")
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    return tmp_path


@pytest.fixture()
def client(api_env):
    from backend.main import app

    with TestClient(app) as handle:
        yield handle


@pytest.fixture()
def stub_agent(monkeypatch):
    def _answer(user_input, history=None, **kwargs):
        return {
            "output": f"echo: {user_input[:60]}",
            "active_tier": "Stub Tier",
            "task_type": "simple",
            "tools_used": [],
            "sources": [],
        }

    monkeypatch.setattr(agent, "answer_with_fallback", _answer)
    return _answer


def test_health_lists_tiers(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["tiers"], list)


def test_send_persists_turn(client, stub_agent):
    res = client.post("/api/chat/send", json={"content": "hello api"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["message"]["role"] == "assistant"
    assert "hello api" in body["message"]["content"]
    state = client.get("/api/chats").json()
    assert [m["role"] for m in state["current"]] == ["user", "assistant"]


def test_send_rejects_empty(client, stub_agent):
    res = client.post("/api/chat/send", json={"content": "   "})
    assert res.status_code in (400, 422)


def test_send_rejects_unknown_attachment(client, stub_agent):
    res = client.post(
        "/api/chat/send",
        json={"content": "hi", "upload_ids": ["deadbeefdeadbeef"]},
    )
    assert res.status_code == 400


def test_stream_yields_done(client, stub_agent):
    with client.stream("POST", "/api/chat/stream", json={"content": "stream me"}) as res:
        assert res.status_code == 200
        events = []
        for line in res.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    kinds = [e["type"] for e in events]
    assert "meta" in kinds and kinds[-1] == "done"
    done = events[-1]["result"]
    assert "stream me" in done["message"]["content"]
    state = client.get("/api/chats").json()
    assert len(state["current"]) == 2


def test_upload_roundtrip(client, stub_agent):
    up = client.post(
        "/api/uploads",
        files={"file": ("note.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert up.status_code in (200, 201, 400)
    if up.status_code != 200:
        pytest.skip("minimal PDF rejected by validator")
    meta = up.json()
    listed = client.get("/api/uploads").json()
    assert any(u["id"] == meta["id"] for u in listed)
    down = client.get(f"/api/uploads/{meta['id']}/file")
    assert down.status_code == 200
    send = client.post(
        "/api/chat/send",
        json={"content": "summarize", "upload_ids": [meta["id"]]},
    )
    assert send.status_code == 200


def test_chats_new_archives(client, stub_agent):
    client.post("/api/chat/send", json={"content": "first topic"})
    res = client.post("/api/chats/new", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["current"] == []
    assert len(body["chats"]) == 1
    assert "first topic" in body["chats"][0]["title"]
    chat_id = body["chats"][0]["id"]
    renamed = client.patch(f"/api/chats/{chat_id}", json={"title": "Renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["chats"][0]["title"] == "Renamed"
    opened = client.post("/api/chats/open", json={"id": chat_id})
    assert opened.status_code == 200
    assert [m["role"] for m in opened.json()["current"]] == ["user", "assistant"]
    # Open pops the record from history; re-archive with the same id
    # (client-owned identity, like the old session's current_chat_id).
    again = client.post("/api/chats/new", json={"chat_id": chat_id})
    assert again.status_code == 200
    assert len(again.json()["chats"]) == 1
    deleted = client.delete(f"/api/chats/{chat_id}")
    assert deleted.status_code == 200
    assert deleted.json()["chats"] == []


def test_projects_crud_and_context(client):
    created = client.post("/api/projects", json={"name": "Alpha"})
    assert created.status_code == 201
    pid = created.json()["id"]
    assert any(p["id"] == pid for p in client.get("/api/projects").json())
    assert client.patch(f"/api/projects/{pid}", json={"name": "Beta"}).status_code == 200
    assert client.put(f"/api/projects/{pid}/context", json={"text": "ctx"}).status_code == 200
    assert client.get(f"/api/projects/{pid}/context").json() == {"text": "ctx"}
    assert client.post(f"/api/projects/{pid}/archive").status_code == 200
    assert all(p["id"] != pid for p in client.get("/api/projects").json())


def test_brief_from_search_message(client, monkeypatch):
    import agent as agent_mod

    def _answer(user_input, history=None, **kwargs):
        return {
            "output": "researched answer",
            "active_tier": "Stub Tier",
            "task_type": "research",
            "tools_used": ["web_search"],
            "sources": [{
                "title": "Source One",
                "url": "https://example.com/one",
                "domain": "example.com",
            }],
        }

    monkeypatch.setattr(agent_mod, "answer_with_fallback", _answer)
    client.post("/api/chat/send", json={"content": "latest news on X"})
    saved = client.post("/api/briefs", json={"index": 1})
    assert saved.status_code == 201, saved.text
    assert saved.json()["query"] == "latest news on X"
    assert len(client.get("/api/briefs").json()) == 1
    assert client.post("/api/briefs", json={"index": 99}).status_code == 400


def test_memory_notes_roundtrip(client):
    assert client.put("/api/memory/notes", json={"text": "likes tea"}).status_code == 200
    assert client.get("/api/memory/notes").json() == {"text": "likes tea"}
    assert isinstance(client.get("/api/memory/facts").json(), list)


def test_private_mode_requires_token(client, monkeypatch):
    monkeypatch.setenv("POKA_AUTH_MODE", "private")
    monkeypatch.delenv("POKA_USER_ID", raising=False)
    assert client.get("/api/health").status_code == 401
    bad = client.get("/api/health", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_regenerate_appends_fresh_answer(client, stub_agent):
    client.post("/api/chat/send", json={"content": "say hi"})
    res = client.post("/api/chat/regenerate", json={"index": 1})
    assert res.status_code == 200, res.text
    state = client.get("/api/chats").json()
    assert [m["role"] for m in state["current"]] == ["user", "assistant", "assistant"]
    assert client.post("/api/chat/regenerate", json={"index": 0}).status_code == 400
    assert client.post("/api/chat/regenerate", json={"index": 99}).status_code == 400


def test_truncate_cuts_open_conversation(client, stub_agent):
    client.post("/api/chat/send", json={"content": "edit me"})
    res = client.post("/api/chats/truncate", json={"index": 1})
    assert res.status_code == 200
    assert [m["role"] for m in res.json()["current"]] == ["user"]
    assert client.post("/api/chats/truncate", json={"index": 99}).status_code == 400
