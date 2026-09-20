"""Chat PDF export (Phase G): organized A4 transcript download.

POST /api/chats/export-pdf renders archived (chat_id) or inline
messages into a structured transcript — per-turn sections with tier
suffix, attachments, sources — and returns an A4 PDF. Internal UI
metadata (corrections, fallback banners) is excluded; leaked critique
scaffolds are stripped.
"""

import io
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
    monkeypatch.setenv("PLUTO_USER_ID", "export-user")
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


def _msgs():
    return [
        {"role": "user", "content": "Do you know Sam Altman?",
         "time": "2026-09-20T03:01:00"},
        {"role": "assistant", "content": "Yes. Sam Altman is the CEO of OpenAI.",
         "time": "2026-09-20T03:01:10", "model": "Groq",
         "corrections": [["altmman", "altman"]],
         "fallback": {"requested": "X", "reason": "y"}},
        {"role": "user", "content": "Tere liye song",
         "time": "2026-09-20T03:08:00",
         "attachments": [{"id": "a1", "kind": "image", "name": "pic.jpg"}]},
        {"role": "assistant", "content": "Tere Liye is from Prince (2010).",
         "time": "2026-09-20T03:10:00", "model": "Gemini 3.5 Flash",
         "sources": [{"title": "Prince (2010 film)",
                       "url": "https://en.wikipedia.org/wiki/Prince_(2010_film)"}]},
    ]


def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    assert len(reader.pages) >= 1
    # A4 media box (595 x 842 pt).
    box = reader.pages[0].mediabox
    assert [float(v) for v in (box.left, box.bottom, box.width, box.height)] == [
        0.0, 0.0, 595.0, 842.0]
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def test_export_inline_pdf(client):
    res = client.post("/api/chats/export-pdf",
                      json={"title": "Do you know Sam Altman?",
                            "messages": _msgs()})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"].endswith('.pdf"')
    text = _pdf_text(res.content)
    assert "Do you know Sam Altman?" in text
    assert "Gemini 3.5 Flash" in text  # tier suffix kept
    assert "Attachments: pic.jpg" in text
    assert "Prince (2010 film)" in text
    # Internal UI metadata excluded: the stored corrections pair
    # ["altmman", "altman"] must not render as an "Interpreted" note.
    assert "Interpreted" not in text


def test_export_strips_critique_scaffold(client):
    leaked = ("### 3. Critical assessment of the draft response\n\ntable\n\n"
              "### 4. Improved response (ready for user)\n\nThe clean answer.")
    res = client.post("/api/chats/export-pdf",
                      json={"title": "t",
                            "messages": [{"role": "assistant", "content": leaked}]})
    assert res.status_code == 200, res.text
    text = _pdf_text(res.content)
    assert "Critical assessment" not in text
    assert "The clean answer." in text


def test_export_archived_chat(client, stub_agent):
    assert client.post("/api/chat/send", json={"content": "hello export"}).status_code == 200
    new = client.post("/api/chats/new", json={}).json()
    chat_id = new["chats"][0]["id"]
    res = client.post("/api/chats/export-pdf", json={"chat_id": chat_id})
    assert res.status_code == 200, res.text
    assert "hello export" in _pdf_text(res.content)


def test_export_unknown_chat_404(client):
    res = client.post("/api/chats/export-pdf", json={"chat_id": "nope"})
    assert res.status_code == 404


def test_export_empty_400(client):
    assert client.post("/api/chats/export-pdf",
                       json={"title": "t", "messages": []}).status_code == 400
    assert client.post("/api/chats/export-pdf", json={}).status_code in (400, 422)
