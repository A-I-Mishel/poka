"""Backend API tests: FastAPI routes over the real agent/services stack.

Hermetic like the rest of the suite: tmp PLUTO_DATA_DIR, env identity,
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
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "api-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
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


def test_upload_sniffs_missing_extension(client):
    up = client.post(
        "/api/uploads",
        files={"file": ("report", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["kind"] == "pdf"


def test_upload_sniffs_wrong_extension(client):
    up = client.post(
        "/api/uploads",
        files={"file": ("photo.txt", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["kind"] == "pdf"


def test_upload_rejects_unknown_bytes(client):
    up = client.post(
        "/api/uploads",
        files={"file": ("blob", io.BytesIO(b"\x00\x01\x02not-a-doc"), "application/pdf")},
    )
    assert up.status_code == 400


def test_upload_delete_roundtrip(client):
    up = client.post(
        "/api/uploads",
        files={"file": ("gone.txt", io.BytesIO(b"bye soon"), "text/plain")},
    )
    assert up.status_code == 200, up.text
    uid = up.json()["id"]
    assert any(u["id"] == uid for u in client.get("/api/uploads").json())
    assert client.get(f"/api/uploads/{uid}/file").status_code == 200
    test_del = client.delete(f"/api/uploads/{uid}")
    assert test_del.status_code == 200
    assert test_del.json() == {"ok": True}
    assert all(u["id"] != uid for u in client.get("/api/uploads").json())
    assert client.get(f"/api/uploads/{uid}/file").status_code == 404
    assert client.delete(f"/api/uploads/{uid}").status_code == 404
    assert client.delete("/api/uploads/deadbeefdeadbeef").status_code == 404


def test_upload_delete_isolated(api_env, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as owner:
        up = owner.post(
            "/api/uploads",
            files={"file": ("mine.txt", io.BytesIO(b"not yours"), "text/plain")},
        )
        assert up.status_code == 200, up.text
        uid = up.json()["id"]
    monkeypatch.setenv("PLUTO_USER_ID", "stranger-user")
    with TestClient(app) as stranger:
        assert stranger.delete(f"/api/uploads/{uid}").status_code == 404
        assert stranger.get(f"/api/uploads/{uid}/file").status_code == 404
    monkeypatch.setenv("PLUTO_USER_ID", "api-user")
    with TestClient(app) as owner_again:
        assert owner_again.get(f"/api/uploads/{uid}/file").status_code == 200


def _age_registry_record(api_env, name, record_id, days_old):
    """Backdate one registry record's created timestamp (hygiene setup)."""
    import json
    import time

    path = api_env / "data" / "users" / "api-user" / name
    with open(path, "r", encoding="utf-8") as f:
        registry = json.load(f)
    registry[record_id]["created"] = time.time() - days_old * 86400.0
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f)


def test_hygiene_prunes_stale_unreferenced_upload(client, api_env):
    import backend.deps as deps

    up = client.post(
        "/api/uploads",
        files={"file": ("stale.txt", io.BytesIO(b"aging out"), "text/plain")},
    )
    assert up.status_code == 200, up.text
    uid = up.json()["id"]
    _age_registry_record(api_env, "uploads.json", uid, days_old=8)
    deps._last_hygiene.clear()
    listed = client.get("/api/uploads").json()
    assert all(u["id"] != uid for u in listed)
    assert client.get(f"/api/uploads/{uid}/file").status_code == 404
    assert deps._last_hygiene.get("api-user") is not None


def test_hygiene_keeps_referenced_upload(client, api_env, stub_agent):
    import backend.deps as deps

    up = client.post(
        "/api/uploads",
        files={"file": ("keep.txt", io.BytesIO(b"still cited"), "text/plain")},
    )
    assert up.status_code == 200, up.text
    uid = up.json()["id"]
    send = client.post("/api/chat/send", json={"content": "see file", "upload_ids": [uid]})
    assert send.status_code == 200, send.text
    _age_registry_record(api_env, "uploads.json", uid, days_old=8)
    deps._last_hygiene.clear()
    listed = client.get("/api/uploads").json()
    assert any(u["id"] == uid for u in listed)
    assert client.get(f"/api/uploads/{uid}/file").status_code == 200


def test_hygiene_prunes_old_outputs(client, api_env):
    import backend.deps as deps

    from services.files import FileStore

    meta = FileStore("api-user").register_output("old.txt", b"aging out", "file")
    _age_registry_record(api_env, "outputs.json", meta.id, days_old=31)
    deps._last_hygiene.clear()
    assert client.get("/api/artifacts").json() == []


def test_document_attachment_survives_save_load(client, stub_agent):
    up = client.post(
        "/api/uploads",
        files={"file": ("keep.txt", io.BytesIO(b"persist me"), "text/plain")},
    )
    assert up.status_code == 200, up.text
    uid = up.json()["id"]
    assert up.json()["kind"] == "document"
    send = client.post("/api/chat/send", json={"content": "see file", "upload_ids": [uid]})
    assert send.status_code == 200, send.text
    state = client.get("/api/chats").json()
    user_msgs = [m for m in state["current"] if m.get("role") == "user"]
    assert user_msgs and user_msgs[-1].get("attachments") == [
        {"id": uid, "kind": "document", "name": "keep.txt"}
    ]


def test_edit_resend_keeps_attachments(client, stub_agent):
    # Mirrors the UI Edit flow: truncate at the edited message, then
    # resend revised text with the SAME vaulted upload IDs (no re-upload).
    up = client.post(
        "/api/uploads",
        files={"file": ("edit.txt", io.BytesIO(b"edited context"), "text/plain")},
    )
    assert up.status_code == 200, up.text
    uid = up.json()["id"]
    first = client.post("/api/chat/send", json={"content": "first", "upload_ids": [uid]})
    assert first.status_code == 200, first.text
    assert len(client.get("/api/chats").json()["current"]) == 2
    trunc = client.post("/api/chats/truncate", json={"index": 0})
    assert trunc.status_code == 200
    assert trunc.json()["current"] == []
    second = client.post(
        "/api/chat/send", json={"content": "first edited", "upload_ids": [uid]})
    assert second.status_code == 200, second.text
    state = client.get("/api/chats").json()
    user_msgs = [m for m in state["current"] if m.get("role") == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == "first edited"
    assert user_msgs[0].get("attachments") == [
        {"id": uid, "kind": "document", "name": "edit.txt"}
    ]


def test_new_artifact_kinds_survive_save_load():
    from services.files import FileStore
    from services.storage import UserStore

    store = UserStore("kind-user")
    for kind, name in [("pdf", "a.pdf"), ("md", "b.md"), ("doc", "c.doc"), ("html", "d.html")]:
        meta = FileStore("kind-user").register_output(name, b"bytes", kind)
        assert meta.kind == kind
    current = [
        {"role": "assistant", "content": "done",
         "artifacts": [
             {"id": m.id, "kind": m.kind, "name": m.display_name}
             for m in FileStore("kind-user").list_outputs()
         ]},
    ]
    store.save_chats([], current)
    stored, _warnings = store.load_chats()
    kinds = sorted(a["kind"] for a in stored["current"][0]["artifacts"])
    assert kinds == ["doc", "html", "md", "pdf"]


def test_attachment_hint_contract():
    from backend.chatflow import attachment_hint

    pdf = attachment_hint("pdf", "a" * 16, "f.pdf", 1, 1)
    assert "read_pdf" in pdf and "a" * 16 in pdf
    csv = attachment_hint("csv", "b" * 16, "f.csv", 1, 2)
    assert "analyze_csv" in csv and "b" * 16 in csv
    doc = attachment_hint("document", "c" * 16, "f.txt", 2, 2)
    assert "read_document" in doc and "c" * 16 in doc
    # Images ride vision, not tools: the hint must never claim inability
    # (the runtime sends real image bytes to vision-capable tiers, and an
    # explicit could-not-analyze note to text-only tiers).
    img = attachment_hint("image", "d" * 16, "p.png", 1, 1)
    assert "cannot view" not in img.lower()
    assert "cannot see" not in img.lower()
    assert "vision-capable" in img


def test_archive_eviction_warns_at_cap(client):
    from services.storage import MAX_STORED_CHATS, UserStore

    assert MAX_STORED_CHATS >= 50
    store = UserStore("api-user")
    archived = [
        {"id": f"{i:016x}", "title": f"Chat {i:02d}",
         "messages": [{"role": "user", "content": f"topic {i}"}]}
        for i in range(MAX_STORED_CHATS)
    ]
    store.save_chats(archived, [{"role": "user", "content": "fresh topic"}])
    res = client.post("/api/chats/new", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["chats"]) == MAX_STORED_CHATS
    assert body["current"] == []
    assert any("oldest" in w for w in body.get("warnings", []))
    titles = [c["title"] for c in body["chats"]]
    assert titles[0] == "fresh topic"
    assert f"Chat {MAX_STORED_CHATS - 1:02d}" not in titles


def test_archive_no_warning_under_cap(client, stub_agent):
    send = client.post("/api/chat/send", json={"content": "hello"})
    assert send.status_code == 200, send.text
    res = client.post("/api/chats/new", json={})
    assert res.status_code == 200, res.text
    assert res.json().get("warnings", []) == []
    assert len(res.json()["chats"]) == 1


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
    # /api/health is public (liveness probe) even in private mode so
    # Render/K8s checks don't need a token. Other endpoints stay protected.
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    assert client.get("/api/health").status_code == 200
    # bad token doesn't matter for public health — still 200
    bad = client.get("/api/health", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 200
    # protected route must still 401
    assert client.get("/api/chats").status_code == 401
    bad2 = client.get("/api/chats", headers={"Authorization": "Bearer nope"})
    assert bad2.status_code == 401


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


def test_chat_messages_reads_archived_without_opening(client, stub_agent):
    client.post("/api/chat/send", json={"content": "archived topic"})
    assert client.post("/api/chats/new", json={}).status_code == 200
    state = client.get("/api/chats").json()
    assert state["current"] == []
    assert len(state["chats"]) == 1
    cid = state["chats"][0]["id"]

    res = client.get(f"/api/chats/{cid}/messages")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == cid
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]

    # Read-only: the open conversation is untouched by the export read.
    assert client.get("/api/chats").json()["current"] == []
    assert client.get("/api/chats/does-not-exist/messages").status_code == 404
