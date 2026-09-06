"""Projects data-foundation tests (Phase 5A).

Stable conversation IDs, optional project_id membership, and the
per-user projects.json registry. Additive + lazy: legacy data without
IDs keeps working as Personal. Hermetic: tmp POKA_DATA_DIR.
"""

import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent  # noqa: F401  (keeps import order consistent with other UI tests)

# Bind the app's from-imports to the REAL service functions before any
# AppTest run (see the import-order note in test_force_search_flow.py).
import application.session  # noqa: F401
import services.auth  # noqa: F401
import ui.chat  # noqa: F401
import ui.components  # noqa: F401
import ui.composer  # noqa: F401
import ui.sidebar  # noqa: F401
import ui.uploads  # noqa: F401
from services.storage import (
    UserStore,
    clean_messages,
    find_chat_by_id,
    is_valid_id,
    new_conversation_id,
)

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _clean_agent_state():
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()


@pytest.fixture()
def proj_env(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    return tmp_path / "data"


def _use_user(monkeypatch, name):
    monkeypatch.setenv("POKA_USER_ID", name)
    return str(UserStore(name).root)


def _run_app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    return at


def _stub_app_agent(monkeypatch, **extra):
    import services.identity as identity

    monkeypatch.setattr(
        identity,
        "get_current_user",
        lambda: identity.UserIdentity(id="u1", email=None, source="env"),
    )
    payload = {"output": "ok", "active_tier": "T", "task_type": "simple"}
    payload.update(extra)

    def fake_answer(user_input, chat_history=None, **kwargs):
        return dict(payload)

    monkeypatch.setattr(agent, "answer_with_fallback", fake_answer)


# -- project CRUD ---------------------------------------------------------

def test_project_create(proj_env):
    store = UserStore("proj-user")
    record = store.create_project("Website")
    assert is_valid_id(record["id"])
    assert record["name"] == "Website"
    assert isinstance(record["created"], float)
    assert record["archived"] is False
    data, warnings = store.load_projects()
    assert warnings == []
    assert data["version"] == 1
    assert data["projects"] == [record]


def test_project_name_validation(proj_env):
    store = UserStore("proj-user")
    for bad in ["", "   ", None]:
        with pytest.raises(ValueError):
            store.create_project(bad)
    assert store.list_projects() == []
    # Non-string names coerce like chat titles do (existing convention).
    assert store.create_project(123)["name"] == "123"
    long_name = "x" * 100
    assert store.create_project(long_name)["name"] == "x" * 60
    assert store.create_project("  spaced  ")["name"] == "spaced"


def test_project_id_validation(proj_env):
    store = UserStore("proj-user")
    assert store.get_project("nope") is None
    assert store.get_project("") is None
    assert store.get_project(None) is None
    assert store.get_project(123) is None
    assert store.get_project("../x") is None
    assert store.get_project("A" * 16) is None  # strict lowercase hex
    assert store.rename_project("nope", "New") is False
    assert store.archive_project("nope") is False
    assert not os.path.exists(store.projects_path)
    assert is_valid_id("a" * 16) and not is_valid_id("a" * 15)


def test_project_rename(proj_env):
    store = UserStore("proj-user")
    pid = store.create_project("Old")["id"]
    assert store.rename_project(pid, "New") is True
    assert store.get_project(pid)["name"] == "New"
    with pytest.raises(ValueError):
        store.rename_project(pid, "   ")
    assert store.get_project(pid)["name"] == "New"
    assert store.rename_project("b" * 16, "New") is False


def test_project_lookup_returns_copies(proj_env):
    store = UserStore("proj-user")
    pid = store.create_project("Site")["id"]
    fetched = store.get_project(pid)
    fetched["name"] = "Mutated"
    assert store.get_project(pid)["name"] == "Site"


def test_project_listing_order(proj_env):
    store = UserStore("proj-user")
    first = store.create_project("One")["id"]
    second = store.create_project("Two")["id"]
    assert [p["id"] for p in store.list_projects()] == [first, second]
    assert store.archive_project(first) is True
    assert [p["id"] for p in store.list_projects()] == [second]
    assert [p["id"] for p in store.list_projects(include_archived=True)] == [
        first, second]


def test_project_archive_persists(proj_env):
    store = UserStore("proj-user")
    pid = store.create_project("Site")["id"]
    assert store.archive_project(pid) is True
    assert store.archive_project(pid) is True  # idempotent
    reloaded = UserStore("proj-user").get_project(pid)
    assert reloaded["archived"] is True
    assert reloaded["name"] == "Site"
    assert is_valid_id(reloaded["id"])


def test_malformed_projects_file(proj_env):
    store = UserStore("proj-user")
    store.projects_path.parent.mkdir(parents=True, exist_ok=True)
    store.projects_path.write_text("{not valid json", encoding="utf-8")
    data, warnings = store.load_projects()
    assert data == {"version": 1, "projects": []}
    assert warnings != []
    assert list(store.projects_path.parent.glob("projects.corrupt-*")) != []


def test_malformed_project_records_skipped(proj_env):
    store = UserStore("proj-user")
    good = {"id": "a" * 16, "name": "Good", "created": 1700000000.0,
            "archived": False}
    store.save_projects([
        good,
        {"no": "id"},
        {"id": "bad", "name": "Bad id"},
        {"id": "b" * 16, "name": "   "},
        {"id": "c" * 16, "name": "Coerced", "created": "x", "archived": "yes"},
        "junk",
    ])
    data, _ = store.load_projects()
    by_id = {p["id"]: p for p in data["projects"]}
    assert set(by_id) == {"a" * 16, "c" * 16}
    assert by_id["a" * 16]["name"] == "Good"
    assert by_id["c" * 16]["created"] == 0.0
    assert by_id["c" * 16]["archived"] is False


def test_projects_isolated_per_user(proj_env):
    alice = UserStore("proj-alice")
    pid = alice.create_project("Site")["id"]
    bob = UserStore("proj-bob")
    assert bob.list_projects() == []
    assert bob.get_project(pid) is None
    assert bob.rename_project(pid, "X") is False
    assert bob.archive_project(pid) is False
    assert alice.get_project(pid)["name"] == "Site"


def test_concurrent_creates_stay_valid(proj_env):
    # Characterization: per-file lock + atomic replace keep the registry
    # parseable and complete under threads; same-record races would be
    # last-writer-wins (documented, not solved here).
    store = UserStore("proj-user")
    errors = []

    def _make(n):
        try:
            store.create_project(f"P{n}")
        except Exception as e:  # noqa: BLE001 (record only)
            errors.append(e)

    threads = [threading.Thread(target=_make, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    data, _ = store.load_projects()
    assert len(data["projects"]) == 8
    assert len({p["id"] for p in data["projects"]}) == 8


# -- conversation IDs ------------------------------------------------------

def test_conversation_id_generation():
    ids = {new_conversation_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(is_valid_id(i) for i in ids)


def test_chat_id_round_trip(proj_env):
    store = UserStore("proj-user")
    chats = [{"id": "a" * 16, "title": "T",
              "messages": [{"role": "user", "content": "hi"}]}]
    store.save_chats(chats, [])
    loaded, _ = store.load_chats()
    assert loaded["chats"][0]["id"] == "a" * 16
    assert "project_id" not in loaded["chats"][0]


def test_legacy_chat_round_trip_exact(proj_env):
    store = UserStore("proj-user")
    legacy = {"title": "Old", "messages": [
        {"role": "user", "content": "hi", "time": "t"},
        {"role": "assistant", "content": "yo"},
    ]}
    store.save_chats([legacy], [])
    loaded, warnings = store.load_chats()
    assert warnings == []
    assert loaded["chats"] == [legacy]
    assert "id" not in loaded["chats"][0]


def test_project_id_cleaner(proj_env):
    store = UserStore("proj-user")
    pid = store.create_project("Site")["id"]
    good = {"title": "T", "project_id": pid, "messages": []}
    bad = {"title": "T", "project_id": "../x", "messages": []}
    wrong_type = {"title": "T", "project_id": 123, "messages": []}
    bare = {"title": "T", "messages": []}
    store.save_chats([good, bad, wrong_type, bare], [])
    loaded, _ = store.load_chats()
    assert loaded["chats"][0]["project_id"] == pid
    for record in loaded["chats"][1:]:
        assert "project_id" not in record  # absent, never null


def test_orphan_project_id_preserved(proj_env):
    # Unknown-but-valid references survive storage verbatim (no data
    # loss); consumers treat them as Personal until project UI lands.
    store = UserStore("proj-user")
    store.save_chats([{"title": "T", "project_id": "f" * 16,
                       "messages": []}], [])
    loaded, _ = store.load_chats()
    assert loaded["chats"][0]["project_id"] == "f" * 16


def test_find_chat_by_id(proj_env):
    store = UserStore("proj-user")
    store.save_chats([
        {"id": "a" * 16, "title": "First", "messages": []},
        {"title": "Legacy", "messages": []},
    ], [])
    loaded, _ = store.load_chats()
    found = find_chat_by_id(loaded["chats"], "a" * 16)
    assert found is not None and found["title"] == "First"
    found["title"] = "Mutated"
    assert find_chat_by_id(loaded["chats"], "a" * 16)["title"] == "First"
    assert find_chat_by_id(loaded["chats"], "nope") is None
    assert find_chat_by_id(loaded["chats"], "../x") is None
    assert find_chat_by_id([], "a" * 16) is None
    assert find_chat_by_id("junk", "a" * 16) is None


def test_rich_message_round_trip(proj_env):
    store = UserStore("proj-user")
    msgs = [{
        "role": "user", "content": "go", "time": "t",
        "attachments": [{"id": "a" * 16, "kind": "pdf", "name": "r.pdf"}],
    }, {
        "role": "assistant", "content": "done", "time": "t",
        "model": "T", "mode": "deep", "searched": True,
        "search_executed": True, "tools": ["web_search"],
        "sources": [{"title": "S", "url": "https://e.example/",
                     "domain": "e.example"}],
        "artifacts": [{"id": "b" * 16, "kind": "pptx", "name": "B.pptx"}],
    }]
    store.save_chats([{"id": "c" * 16, "title": "T", "project_id": "d" * 16,
                       "messages": msgs}], msgs)
    loaded, _ = store.load_chats()
    assert loaded["chats"][0]["messages"] == msgs
    assert loaded["current"] == msgs
    assert loaded["chats"][0]["id"] == "c" * 16
    assert loaded["chats"][0]["project_id"] == "d" * 16


def test_memory_stores_untouched(proj_env):
    store = UserStore("proj-user")
    store.save_notes("NOTE-XYZ")
    store.save_structured({"preferences": {}, "facts": [], "past_tasks": [],
                           "user_name": None})
    store.create_project("Site")
    store.save_chats([{"id": "a" * 16, "title": "T", "messages": []}], [])
    assert store.load_notes() == "NOTE-XYZ"
    mem, _ = store.load_structured()
    assert mem["facts"] == []


# -- AppTest: ID lifecycle ---------------------------------------------------

def test_legacy_archive_assigns_id(proj_env, monkeypatch):
    _use_user(monkeypatch, "proj-legacy")
    _stub_app_agent(monkeypatch)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.session_state.messages = [{"role": "user", "content": "hello past"}]
    at.session_state.chats = []
    at.run(timeout=60)
    at.button(key="new-chat").click().run(timeout=120)
    assert not at.exception
    archived = at.session_state.chats[0]
    assert is_valid_id(archived.get("id"))
    assert archived["title"] == "hello past"
    assert archived["messages"] == [{"role": "user", "content": "hello past"}]
    assert "project_id" not in archived
    assert at.session_state.messages == []
    assert at.session_state["current_chat_id"] is None


def test_new_conversation_gets_stable_id(proj_env, monkeypatch):
    _use_user(monkeypatch, "proj-new")
    _stub_app_agent(monkeypatch)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.session_state.messages = []
    at.session_state.chats = []
    at.run(timeout=60)
    at.text_input(key="composer_input_0").set_value("hi").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    first_id = at.session_state["current_chat_id"]
    assert is_valid_id(first_id)
    at.text_input(key="composer_input_1").set_value("again").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assert at.session_state["current_chat_id"] == first_id


def test_select_preserves_id(proj_env, monkeypatch):
    _use_user(monkeypatch, "proj-select")
    _stub_app_agent(monkeypatch)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.session_state.messages = []
    at.session_state.chats = [{
        "id": "a" * 16, "title": "Old",
        "messages": [{"role": "user", "content": "old q"}],
    }]
    at.run(timeout=60)
    at.button(key="hist-0").click().run(timeout=120)
    assert not at.exception
    assert at.session_state["current_chat_id"] == "a" * 16
    assert [m["content"] for m in at.session_state.messages] == ["old q"]
    at.button(key="new-chat").click().run(timeout=120)
    assert not at.exception
    assert at.session_state.chats[0]["id"] == "a" * 16
    # Re-archive re-derives the title from content (existing behavior);
    # the stable ID is what must survive.
    assert at.session_state.chats[0]["title"] == "old q"
