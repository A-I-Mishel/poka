"""Gmail tests: formatting, body extraction, safety gates (all stubbed).

A fake service emulates the googleapiclient method chain; no network,
no credentials, no quota.
"""

import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services import gmail as gmail_svc
from tools.gmail_tool import create_gmail_draft, read_gmail, search_gmail, send_gmail


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode()


FULL_MESSAGE = {
    "id": "msg-1",
    "snippet": "quarterly numbers attached",
    "payload": {
        "mimeType": "multipart/alternative",
        "headers": [
            {"name": "Subject", "value": "Q3 numbers"},
            {"name": "From", "value": "boss@example.com"},
            {"name": "Date", "value": "Mon, 01 Sep 2026"},
        ],
        "parts": [
            {"mimeType": "text/plain",
             "body": {"data": _b64("Revenue is up 12 percent.")}},
            {"mimeType": "text/html",
             "body": {"data": _b64("<b>Revenue</b> up")}},
        ],
    },
}

HTML_ONLY = {
    "mimeType": "text/html",
    "headers": [],
    "body": {"data": _b64("<p>hi</p>")},
}


class _Call:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._payload


class _Messages:
    def __init__(self, store):
        self._store = store

    def list(self, userId=None, q=None, maxResults=None):
        ids = [{"id": mid} for mid in list(self._store)[: maxResults or 10]]
        return _Call({"messages": ids})

    def get(self, userId=None, id=None, format=None, metadataHeaders=None):
        if id not in self._store:
            return _Call(error=Exception("not found"))
        return _Call(self._store[id])

    def send(self, userId=None, body=None):
        return _Call({"id": "sent-1"})


class _Drafts:
    def create(self, userId=None, body=None):
        assert body and body.get("message", {}).get("raw")
        return _Call({"id": "draft-1"})


class _Users:
    def __init__(self, store):
        self._store = store

    def messages(self):
        return _Messages(self._store)

    def drafts(self):
        return _Drafts()


class FakeGmailService:
    def __init__(self, store):
        self._store = store

    def users(self):
        return _Users(self._store)


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx.set_current_user_id("gmail-user")
    ctx.set_limit_key("gmail-user")
    gmail_svc.configure_service(FakeGmailService({"msg-1": FULL_MESSAGE}))
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)
    gmail_svc.configure_service(None)


def test_search_formats_hits():
    out = search_gmail.invoke({"query": "numbers"})
    assert "Q3 numbers" in out
    assert "boss@example.com" in out
    assert "msg-1" in out


def test_search_empty():
    gmail_svc.configure_service(FakeGmailService({}))
    assert search_gmail.invoke({"query": "zzz"}).startswith("STATUS=EMPTY")


def test_read_returns_body():
    out = read_gmail.invoke({"message_id": "msg-1"})
    assert "Revenue is up 12 percent." in out
    assert "Q3 numbers" in out


def test_read_unknown_id():
    assert read_gmail.invoke({"message_id": "nope"}).startswith("STATUS=FAILED")


def test_extract_plain_prefers_text():
    assert gmail_svc.extract_plain_text(FULL_MESSAGE["payload"]) == "Revenue is up 12 percent."


def test_extract_plain_html_fallback():
    assert gmail_svc.extract_plain_text(HTML_ONLY) == "<p>hi</p>"


def test_extract_plain_garbage():
    assert gmail_svc.extract_plain_text({}) == ""
    assert gmail_svc.extract_plain_text(None) == ""


def test_draft_and_send():
    assert "draft-1" in create_gmail_draft.invoke(
        {"to": "a@example.com", "subject": "hi", "body": "hello"})
    assert "sent-1" in send_gmail.invoke(
        {"to": "a@example.com", "subject": "hi", "body": "hello", "confirm": True})


def test_send_requires_confirmation():
    out = send_gmail.invoke({"to": "a@example.com", "subject": "hi", "body": "hello"})
    assert out.startswith("STATUS=DENIED")


def test_bad_recipient():
    assert create_gmail_draft.invoke(
        {"to": "not-an-email", "subject": "x", "body": "y"}).startswith("STATUS=INVALID")


def test_unconfigured_degrades(monkeypatch):
    gmail_svc.configure_service(None)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    assert search_gmail.invoke({"query": "x"}).startswith("STATUS=DEGRADED")


def test_no_user_denied():
    ctx.set_current_user_id(None)
    assert search_gmail.invoke({"query": "x"}).startswith("STATUS=DENIED")


class FailingGmailService(FakeGmailService):
    def users(self):
        raise RuntimeError("quota hit")


def test_backend_errors_surface_cleanly():
    gmail_svc.configure_service(FailingGmailService({}))
    with pytest.raises(RuntimeError, match="Gmail search failed"):
        gmail_svc.search_messages(gmail_svc.get_service(), "x")
    with pytest.raises(RuntimeError, match="Gmail read failed"):
        gmail_svc.read_message(gmail_svc.get_service(), "abc")
    with pytest.raises(RuntimeError, match="Gmail draft failed"):
        gmail_svc.create_draft(gmail_svc.get_service(), "a@b.c", "s", "body")
    with pytest.raises(RuntimeError, match="Gmail send failed"):
        gmail_svc.send_message(gmail_svc.get_service(), "a@b.c", "s", "body")


def test_tool_maps_backend_errors_to_failed():
    gmail_svc.configure_service(FailingGmailService({}))
    assert search_gmail.invoke({"query": "x"}).startswith("STATUS=FAILED")
