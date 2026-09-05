"""Phase 1 regression tests: isolation, traversal, structured tools,
single-input flow, retry/edit, forced search, cooldowns, corrupt storage.

All tests are local and hermetic: POKA_DATA_DIR points at tmp_path,
POKA_USER_ID fixes identity, and network-touching agent functions are
stubbed. No test spends model quota.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from services import context as ctx

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
from services import files as files_mod
from services import storage as storage_mod
from services.files import FileStore, FileValidationError
from services.storage import StorageError, UserStore


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Keep legacy CWD-relative files out of tests (migration reads them)."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Isolate all service storage per test."""
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("POKA_USER_ID", "test-user")
    ctx.set_current_user_id("test-user")
    yield tmp_path / "data"
    ctx.set_current_user_id(None)


@pytest.fixture(autouse=True)
def _clean_agent_state():
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


def _csv_bytes(rows: int = 3) -> bytes:
    lines = ["a,b"] + [f"{i},{i * 2}" for i in range(rows)]
    return ("\n".join(lines) + "\n").encode()


# -- 2/3. chat + memory isolation -----------------------------------

def test_user_chats_isolated(data_dir):
    UserStore("user-a").save_chats([{"title": "A", "messages": []}], [])
    data, warnings = UserStore("user-b").load_chats()
    assert data == {"chats": [], "current": []}
    assert warnings == []


def test_user_memory_isolated(data_dir):
    UserStore("user-a").save_notes("A secret")
    assert UserStore("user-b").load_notes() == ""


def test_structured_memory_isolated(data_dir):
    UserStore("user-a").save_structured({"preferences": {}, "facts": [], "past_tasks": [], "user_name": "A"})
    mem, _ = UserStore("user-b").load_structured()
    assert mem["user_name"] is None


# -- 4/5/6. upload + output isolation ---------------------------------

def test_uploads_isolated(data_dir):
    meta = FileStore("user-a").save_upload(_pdf_bytes(), "doc.pdf")
    assert FileStore("user-b").get_upload(meta.id) is None
    assert FileStore("user-b").resolve_upload(meta.id) is None
    assert FileStore("user-a").resolve_upload(meta.id) is not None


def test_outputs_isolated_and_owned_delete(data_dir):
    meta = FileStore("user-a").register_output("deck.pptx", b"PPTXBYTES", "pptx")
    assert FileStore("user-b").list_outputs() == []
    assert FileStore("user-b").read_output(meta.id) is None
    assert FileStore("user-b").delete_output(meta.id) is False
    assert FileStore("user-a").read_output(meta.id) == b"PPTXBYTES"
    assert FileStore("user-a").delete_output(meta.id) is True


# -- 7. traversal -------------------------------------------------------

def test_traversal_paths_rejected(data_dir):
    with pytest.raises(StorageError):
        storage_mod.user_dir("../../etc")
    with pytest.raises(StorageError):
        storage_mod.user_dir("")
    store = FileStore("user-a")
    assert store.resolve_upload("../../etc/passwd") is None
    assert store.get_upload("../../../x") is None
    assert store.read_output("/etc/passwd") is None


# -- 8/9. invalid + foreign upload IDs ------------------------------------

def test_invalid_upload_ids_rejected(data_dir):
    from tools.pdf_tool import read_pdf
    from tools.data_tool import analyze_csv

    ctx.set_current_user_id("user-a")
    for bad in ["", "nope", "../x"]:
        assert "STATUS=DENIED" in read_pdf.invoke({"upload_id": bad})
        assert "STATUS=DENIED" in analyze_csv.invoke({"upload_id": bad})
    # Non-string IDs never reach storage: tool schema validation rejects them.
    for bad in [None, 123]:
        with pytest.raises(Exception):
            read_pdf.invoke({"upload_id": bad})


def test_foreign_upload_id_rejected(data_dir):
    from tools.pdf_tool import read_pdf

    ctx.set_current_user_id("user-a")
    meta = FileStore("user-a").save_upload(_pdf_bytes(), "doc.pdf")
    ctx.set_current_user_id("user-b")
    assert "STATUS=DENIED" in read_pdf.invoke({"upload_id": meta.id})


def test_missing_user_context_denies(data_dir):
    from tools.pdf_tool import read_pdf

    ctx.set_current_user_id(None)
    assert "STATUS=INVALID" in read_pdf.invoke({"upload_id": "abcdef1234567890"})


# -- upload validation ------------------------------------------------------

def test_upload_validation(data_dir):
    store = FileStore("user-a")
    with pytest.raises(FileValidationError):
        store.save_upload(b"", "empty.pdf")
    with pytest.raises(FileValidationError):
        store.save_upload(b"not a pdf", "evil.pdf")
    with pytest.raises(FileValidationError):
        store.save_upload(b"print('hi')", "script.py")
    with pytest.raises(FileValidationError):
        store.save_upload(b"../../x", "ok.pdf")
    meta = store.save_upload(_pdf_bytes(), "  dir/../ok.pdf ")
    assert ".." not in meta.stored_name
    assert meta.kind == "pdf"


def test_upload_size_cap(data_dir, monkeypatch):
    monkeypatch.setattr(files_mod, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(FileValidationError) as e:
        FileStore("user-a").save_upload(b"x" * 11, "big.pdf")
    assert "large" in str(e.value)


# -- 12. structured tool results ----------------------------------------------

def test_tool_results_structured(data_dir, monkeypatch):
    class Stub:
        name = "stub"
        calls = 0

        def invoke(self, args):
            type(self).calls += 1
            return "hello"

    class Boom:
        name = "boom"

        def invoke(self, args):
            raise ValueError("kaput")

    monkeypatch.setitem(agent.TOOL_MAP, "stub", Stub())
    monkeypatch.setitem(agent.TOOL_MAP, "boom", Boom())
    ok = agent._execute_tool_call({"name": "stub", "args": {}})
    assert ok.startswith("STATUS=OK") and "<untrusted_tool_output>" in ok
    assert agent._execute_tool_call({"name": "nope", "args": {}}).startswith("STATUS=INVALID")
    failed = agent._execute_tool_call({"name": "boom", "args": {}})
    assert failed.startswith("STATUS=FAILED") and "kaput" in failed


def test_empty_tool_result_marked(data_dir, monkeypatch):
    class Blank:
        name = "blank"

        def invoke(self, args):
            return "   "

    monkeypatch.setitem(agent.TOOL_MAP, "blank", Blank())
    assert agent._execute_tool_call({"name": "blank", "args": {}}).startswith("STATUS=EMPTY")


def test_bounded_call_times_out():
    with pytest.raises(TimeoutError):
        agent._call_bounded(lambda: time.sleep(2), 0.02, "test op")


# -- 11. cooldown policy ---------------------------------------------------------

def test_skipped_provider_not_selected():
    calls = []

    def bad_getter():
        calls.append("bad")
        raise ConnectionError("down")

    def good_getter():
        calls.append("good")
        return object()

    tiers = [("bad", bad_getter), ("good", good_getter)]
    name, _ = agent._run_cascade_step(lambda _n, llm: "ok", None, tiers)
    assert name == "good"
    assert agent._tier_skipped("bad")
    calls.clear()
    name2, _ = agent._run_cascade_step(lambda _n, llm: "ok2", None, tiers)
    assert name2 == "good"
    assert calls == ["good"]  # bad tier never attempted while cooling


# -- 10. forced web search executes -----------------------------------------------

class _NoToolLLM:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        class R:
            content = "done"

        return R()


def test_forced_search_executes(monkeypatch):
    seen = {}

    class SearchStub:
        name = "web_search"

        def invoke(self, args):
            seen["query"] = args.get("query", "")
            return "search says hi"

    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    out = agent.run_tool_loop(_NoToolLLM(), "tell me news", [], force_web_search=True)
    assert seen.get("query"), "web_search was never executed"
    assert out == "done"


def test_max_rounds_synthesis():
    class AlwaysTool:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            if any("Summarize the tool results" in str(getattr(m, "content", "")) for m in messages):
                class R:
                    content = "synthesized"

                    def __getattr__(self, item):
                        if item == "tool_calls":
                            return []
                        raise AttributeError(item)

                return R()

            class T:
                content = ""
                tool_calls = [{"name": "missing-tool-xyz", "args": {}}]

            return T()

    out = agent.run_tool_loop(AlwaysTool(), "do thing", [], max_rounds=1)
    assert out == "synthesized"


# -- validation caps ---------------------------------------------------------------

def test_csv_row_cap(data_dir, monkeypatch):
    import tools.data_tool as data_tool

    monkeypatch.setattr(data_tool, "MAX_CSV_ROWS", 10)
    ctx.set_current_user_id("user-a")
    meta = FileStore("user-a").save_upload(_csv_bytes(20), "big.csv")
    out = data_tool.analyze_csv.invoke({"upload_id": meta.id})
    assert "limited to the first 10 rows" in out


def test_legacy_migration_imports_once(data_dir, tmp_path):
    legacy = tmp_path / "memory"
    legacy.mkdir()
    (legacy / "chats.json").write_text(
        '{"chats": [{"title": "Old", "messages": []}], "current": []}',
        encoding="utf-8",
    )
    (legacy / "memory.md").write_text("old notes", encoding="utf-8")
    store = UserStore("fresh-user")
    data, _ = store.load_chats()
    assert data["chats"] and data["chats"][0]["title"] == "Old"
    assert store.load_notes() == "old notes"
    # Second store for the same user must NOT re-import (no duplication).
    store2 = UserStore("fresh-user")
    data2, _ = store2.load_chats()
    assert len(data2["chats"]) == 1


def test_corrupt_storage_recovered_with_warning(data_dir):
    store = UserStore("user-a")
    store.chats_path.parent.mkdir(parents=True, exist_ok=True)
    store.chats_path.write_text("{not json", encoding="utf-8")
    data, warnings = store.load_chats()
    assert data == {"chats": [], "current": []}
    assert warnings, "expected a corruption warning"
    backups = list(store.root.glob("chats.corrupt-*"))
    assert backups, "expected a quarantined backup file"


# -- 1/13/14. app flows (no network: stubbed agent) -------------------------------------


def test_single_input_no_duplicates(monkeypatch, tmp_path):
    import services.identity as identity

    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setattr(identity, "get_current_user", lambda: identity.UserIdentity(id="u1", email=None, source="env"))
    monkeypatch.setattr(
        agent,
        "answer_with_fallback",
        lambda *a, **k: {"output": "pong", "active_tier": "T", "task_type": "simple"},
    )
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.text_input(key="composer_input_0").set_value("hi").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=60)
    assert not at.exception, f"send failed: {at.exception}"
    users = [m for m in at.session_state.messages if m["role"] == "user"]
    assistants = [m for m in at.session_state.messages if m["role"] == "assistant"]
    assert len(users) == 1 and users[0]["content"] == "hi"
    assert len(assistants) == 1 and assistants[0]["content"] == "pong"


def test_retry_no_duplicates(monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(identity, "get_current_user", lambda: identity.UserIdentity(id="u1", email=None, source="env"))
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"output": "recovered", "active_tier": "T", "task_type": "simple"}

    monkeypatch.setattr(agent, "answer_with_fallback", flaky)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.text_input(key="composer_input_0").set_value("hi").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    users = [m for m in at.session_state.messages if m["role"] == "user"]
    assert len(users) == 1
    assert at.session_state.messages[-1]["role"] == "user"  # no answer yet
    at.button(key="retry-main").click().run(timeout=120)
    assert not at.exception, f"retry failed: {at.exception}"
    users = [m for m in at.session_state.messages if m["role"] == "user"]
    assistants = [m for m in at.session_state.messages if m["role"] == "assistant"]
    assert len(users) == 1, users
    assert len(assistants) == 1 and assistants[0]["content"] == "recovered"


def test_edit_restores_attachments(monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(identity, "get_current_user", lambda: identity.UserIdentity(id="u1", email=None, source="env"))
    monkeypatch.setattr(
        agent,
        "answer_with_fallback",
        lambda *a, **k: {"output": "ok", "active_tier": "T", "task_type": "simple"},
    )
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.session_state.messages = [
        {
            "role": "user",
            "content": "read this",
            "attachments": [{"id": "a" * 16, "kind": "pdf", "name": "doc.pdf"}],
        },
        {"role": "assistant", "content": "done"},
    ]
    at.session_state.chats = []
    at.run(timeout=120)
    at.button(key="edit-0").click().run(timeout=120)
    assert not at.exception, f"edit failed: {at.exception}"
    pending = at.session_state.pending_attach
    assert isinstance(pending, dict) and pending["upload_id"] == "a" * 16
    assert at.session_state.messages == []
    ckey = f"composer_input_{at.session_state.composer_key}"
    assert at.session_state[ckey] == "read this"

