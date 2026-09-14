"""Calendar tests: formatting, validation, safety gates (all stubbed)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import calendar as calendar_svc
from services import context as ctx
from tools.calendar_tool import (
    create_calendar_event,
    delete_calendar_event,
    list_calendar_events,
)

EVENTS = [
    {"id": "ev-1", "summary": "Team standup",
     "start": {"dateTime": "2026-09-13T10:00:00+06:00"},
     "end": {"dateTime": "2026-09-13T10:30:00+06:00"},
     "location": "Office", "htmlLink": "http://x/1"},
    {"id": "ev-2", "summary": "Dentist day",
     "start": {"date": "2026-09-14"}, "end": {"date": "2026-09-15"}},
]


class _Call:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._payload


class _Events:
    def __init__(self):
        self.created = []
        self.deleted = []

    def list(self, calendarId=None, timeMin=None, maxResults=None,
             singleEvents=None, orderBy=None, **kwargs):
        q = str(kwargs.get("q", "") or "").lower()
        items = [e for e in EVENTS
                 if not q or q in str(e.get("summary", "")).lower()]
        return _Call({"items": items[: maxResults or 25]})

    def insert(self, calendarId=None, body=None):
        self.created.append(dict(body or {}))
        return _Call({"id": "new-1", "htmlLink": "http://x/new"})

    def delete(self, calendarId=None, eventId=None):
        if eventId == "missing":
            return _Call(error=Exception("not found"))
        self.deleted.append(eventId)
        return _Call({})


class FakeCalendarService:
    def __init__(self):
        self.events_obj = _Events()

    def events(self):
        return self.events_obj


@pytest.fixture()
def fake():
    svc = FakeCalendarService()
    calendar_svc.configure_service(svc)
    try:
        yield svc
    finally:
        calendar_svc.configure_service(None)


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    ctx.set_current_user_id("cal-user")
    ctx.set_limit_key("cal-user")
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)


def test_list_formats(fake):
    out = list_calendar_events.invoke({})
    assert "Team standup" in out
    assert "2026-09-13T10:00:00+06:00 -> 2026-09-13T10:30:00+06:00" in out
    assert "Office" in out
    assert "Dentist day" in out
    assert "2026-09-14" in out


def test_list_query_filter(fake):
    out = list_calendar_events.invoke({"query": "dentist"})
    assert "Dentist day" in out
    assert "Team standup" not in out


def test_list_empty(fake):
    out = list_calendar_events.invoke({"query": "zzz-no-match"})
    assert out.startswith("STATUS=EMPTY")


def test_create_ok_and_default_hour(fake):
    out = create_calendar_event.invoke({
        "summary": "Focus block", "start": "2026-09-13T10:00:00+06:00"})
    assert "event_id=new-1" in out
    body = fake.events_obj.created[0]
    assert body["end"]["dateTime"] == "2026-09-13T11:00:00+06:00"


def test_create_bad_time(fake):
    out = create_calendar_event.invoke({"summary": "x", "start": "not-a-time"})
    assert out.startswith("STATUS=INVALID")


def test_create_missing_fields(fake):
    assert create_calendar_event.invoke({"summary": "", "start": ""}).startswith("STATUS=INVALID")


def test_delete_requires_confirmation(fake):
    out = delete_calendar_event.invoke({"event_id": "ev-1"})
    assert out.startswith("STATUS=DENIED")
    assert fake.events_obj.deleted == []


def test_delete_confirmed(fake):
    out = delete_calendar_event.invoke({"event_id": "ev-1", "confirm": True})
    assert "deleted_id=ev-1" in out
    assert fake.events_obj.deleted == ["ev-1"]


def test_delete_missing(fake):
    assert delete_calendar_event.invoke(
        {"event_id": "missing", "confirm": True}).startswith("STATUS=FAILED")


def test_unconfigured_degrades(monkeypatch):
    calendar_svc.configure_service(None)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    assert list_calendar_events.invoke({}).startswith("STATUS=DEGRADED")


def test_no_user_denied():
    ctx.set_current_user_id(None)
    assert list_calendar_events.invoke({}).startswith("STATUS=DENIED")


def test_open_mode_denied(monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "open")
    assert list_calendar_events.invoke({}).startswith("STATUS=DENIED")


def test_summarize_tolerates_garbage():
    s = calendar_svc.summarize_event(None)
    assert s["summary"] == "(unreadable)"
    s = calendar_svc.summarize_event({"id": "x"})
    assert s["summary"] == "(no title)" and s["when"] == "?"
