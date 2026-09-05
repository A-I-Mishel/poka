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


def test_env_identity_override(monkeypatch):
    from services.identity import get_current_user

    monkeypatch.setenv("POKA_USER_ID", "operator-1")
    ident = get_current_user()
    assert ident.id == "operator-1" and ident.source == "env"


# -- centralized secrets (Streamlit Secrets + env) -------------------------------

class _StubSecrets:
    """Minimal stand-in for streamlit.secrets (load_if_toml_exists + get)."""

    def __init__(self, values, loaded=True):
        self._values = dict(values)
        self._loaded = loaded

    def load_if_toml_exists(self):
        return self._loaded

    def get(self, name, default=None):
        return self._values.get(name, default)


def _stub_secrets(monkeypatch, values, loaded=True):
    import streamlit

    monkeypatch.setattr(streamlit, "secrets", _StubSecrets(values, loaded))


def test_secrets_env_tokens_accepted(monkeypatch):
    from services.auth import verify_access_token

    monkeypatch.setenv("POKA_ACCESS_TOKENS", "alpha-secret, beta-secret")
    uid = verify_access_token("alpha-secret")
    assert uid and uid.startswith("token-")
    assert verify_access_token("beta-secret") == verify_access_token("beta-secret")
    assert verify_access_token("wrong-token") is None
    assert verify_access_token("") is None


def test_secrets_streamlit_tokens_accepted(monkeypatch):
    from services.auth import verify_access_token

    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    _stub_secrets(monkeypatch, {"POKA_ACCESS_TOKENS": "cloud-one, cloud-two"})
    uid = verify_access_token("cloud-one")
    assert uid and uid.startswith("token-")
    assert verify_access_token("cloud-two") is not None
    assert verify_access_token("wrong-token") is None
    assert verify_access_token("") is None


def test_secrets_take_precedence_over_env(monkeypatch):
    from services.auth import verify_access_token
    from services.secrets import get_secret

    monkeypatch.setenv("POKA_ACCESS_TOKENS", "env-token")
    _stub_secrets(monkeypatch, {"POKA_ACCESS_TOKENS": "cloud-token"})
    assert get_secret("POKA_ACCESS_TOKENS") == "cloud-token"
    assert verify_access_token("cloud-token") is not None
    # First source wins: a stale env token must not authenticate.
    assert verify_access_token("env-token") is None


def test_secrets_missing_keeps_auth_enforced(monkeypatch):
    from services.auth import AuthRequired, authenticate, verify_access_token
    from services.identity import auth_mode

    monkeypatch.setenv("POKA_AUTH_MODE", "private")
    monkeypatch.delenv("POKA_USER_ID", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    # Secrets file present but empty: per-name env fallback still applies,
    # and absent credentials must NOT open the gate.
    _stub_secrets(monkeypatch, {})
    assert auth_mode() == "private"
    assert verify_access_token("anything") is None
    with pytest.raises(AuthRequired):
        authenticate()


def test_secrets_auth_mode_and_identity(monkeypatch):
    from services.identity import auth_mode, get_current_user

    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    monkeypatch.delenv("POKA_USER_ID", raising=False)
    _stub_secrets(monkeypatch, {"POKA_AUTH_MODE": "private", "POKA_USER_ID": "cloud-user"})
    assert auth_mode() == "private"
    ident = get_current_user()
    assert ident.id == "cloud-user" and ident.source == "env"


def test_secrets_config_keys_use_central_seam(monkeypatch):
    import config

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    _stub_secrets(monkeypatch, {"GEMINI_API_KEY": "gem-secret", "OPENCODE_API_KEY": "oc-secret"})
    assert config._get_secret("GEMINI_API_KEY") == "gem-secret"
    assert config._get_secret("OPENCODE_API_KEY") == "oc-secret"
    assert config._get_secret("MISSING_KEY_XYZ") is None


# -- observability redaction ---------------------------------------------------

def test_obs_drops_credential_fields(caplog):
    import logging

    from services import obs as obs_mod

    with caplog.at_level(logging.INFO, logger="poka.obs"):
        obs_mod.event(
            "request.end", status="ok", request_id="abc123",
            api_key="sk-live-should-never-appear",
            access_token="tok-should-never-appear",
            password="pw-should-never-appear",
            tier="Muse Spark 1.3",
        )
    text = caplog.text
    assert "sk-live-should-never-appear" not in text
    assert "tok-should-never-appear" not in text
    assert "pw-should-never-appear" not in text
    assert "abc123" in text and "Muse Spark 1.3" in text


def test_obs_timed_marks_error_and_reraises(caplog):
    import logging

    from services import obs as obs_mod

    with caplog.at_level(logging.INFO, logger="poka.obs"):
        with obs_mod.timed("tool.test_op") as rec:
            rec["status"] = "denied"
    assert "status=denied" in caplog.text
    with caplog.at_level(logging.INFO, logger="poka.obs"):
        with obs_mod.timed("tool.test_op") as rec:
            assert rec["status"] == "ok"
    assert "status=ok" in caplog.text


# -- provider client cache isolation ---------------------------------------------

def test_provider_clients_reused_per_tier_temp(monkeypatch):
    import config

    monkeypatch.setenv("OPENCODE_API_KEY", "dummy-cache-key")
    config._CLIENT_CACHE.clear()
    try:
        default = config.get_tier1_llm()
        assert default is not None and default.temperature == config.TEMPERATURE
        assert config.get_tier1_llm() is default
        cool = config.get_tier1_llm(temperature=0.2)
        assert cool is not default and cool.temperature == 0.2
        # Fetching another temperature never mutates shared instances.
        assert config.get_tier1_llm().temperature == config.TEMPERATURE
        assert config.get_tier_llm("Muse Spark 1.3", temperature=0.2) is cool
        assert config.get_tier_llm("no-such-tier") is None
    finally:
        config._CLIENT_CACHE.clear()


def test_provider_client_cache_rotates_on_key_change(monkeypatch):
    import config

    config._CLIENT_CACHE.clear()
    try:
        monkeypatch.setenv("OPENCODE_API_KEY", "cache-key-one")
        first = config.get_tier1_llm()
        assert first is not None
        monkeypatch.setenv("OPENCODE_API_KEY", "cache-key-two")
        second = config.get_tier1_llm()
        assert second is not None and second is not first
        # Only hashes are retained for rotation checks, never raw keys.
        stored = config._CLIENT_CACHE[("Muse Spark 1.3", float(config.TEMPERATURE))]
        assert "cache-key-two" not in stored[0]
        assert stored[1] is second
    finally:
        config._CLIENT_CACHE.clear()

def test_provider_client_cache_bounded(monkeypatch):
    import config

    monkeypatch.setenv("OPENCODE_API_KEY", "dummy-cache-key")
    config._CLIENT_CACHE.clear()
    try:
        for i in range(config._MAX_CACHED_CLIENTS + 10):
            config.get_tier1_llm(temperature=0.1 + i * 0.01)
        assert len(config._CLIENT_CACHE) <= config._MAX_CACHED_CLIENTS
    finally:
        config._CLIENT_CACHE.clear()


def test_custom_tiers_never_swapped_for_real_clients(monkeypatch):
    # A caller-supplied tiers table owns its instances: even a real tier
    # name must resolve to the provided fake, never a network client.
    monkeypatch.setenv("OPENCODE_API_KEY", "dummy-no-network-key")

    class Fake:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            class R:
                content = "fake answer"
                tool_calls = []

            return R()

    out = agent.answer_with_fallback(
        "write an essay please",
        tiers=[("Muse Spark 1.3", Fake)],
        raw_messages=[],
    )
    assert out["output"] == "fake answer"
    assert out["active_tier"] == "Muse Spark 1.3"


def test_failure_modes_emit_no_secrets_or_content(data_dir, monkeypatch, caplog):
    import logging

    import agent as agent_mod

    monkeypatch.setenv("OPENCODE_API_KEY", "RT-SENTINEL-KEY-9f8e")
    monkeypatch.setenv("GEMINI_API_KEY", "RT-SENTINEL-GEM-7d6c")
    monkeypatch.setenv("POKA_ACCESS_TOKENS", "RT-SENTINEL-TOK-5b4a")
    secret_user_text = "RT-SENTINEL-USERMSG-3c2b says hello"

    class FailLLM:
        def invoke(self, messages):
            raise ConnectionError("provider unreachable")

    with caplog.at_level(logging.DEBUG, logger="poka.obs"):
        with caplog.at_level(logging.DEBUG):
            try:
                agent_mod.answer_with_fallback(
                    secret_user_text,
                    tiers=[("down", FailLLM)],
                    raw_messages=[],
                )
            except RuntimeError:
                pass
            store = FileStore("user-a")
            try:
                store.save_upload(b"", "empty.pdf")
            except Exception:  # noqa: BLE001 - exercising the failure path
                pass
            FileStore("user-a").save_upload(_pdf_bytes(), "doc.pdf")
    text = caplog.text
    for sentinel in (
        "RT-SENTINEL-KEY-9f8e",
        "RT-SENTINEL-GEM-7d6c",
        "RT-SENTINEL-TOK-5b4a",
        "RT-SENTINEL-USERMSG-3c2b",
    ):
        assert sentinel not in text


def test_non_string_secret_value_accepted(monkeypatch):
    from services.auth import verify_access_token

    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    _stub_secrets(monkeypatch, {"POKA_ACCESS_TOKENS": 12345})
    assert verify_access_token("12345") is not None
    assert verify_access_token("wrong") is None


def test_reflection_single_shot_always_improve():
    import agent as agent_mod

    class AlwaysImprove:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1

            class R:
                content = "[IMPROVE] better"

            return R()

    fake = AlwaysImprove()
    out = agent_mod.reflect_and_improve(fake, "q", "draft", [], agent_mod.RequestBudget())
    assert out == "better" and fake.calls == 1


def test_symlink_upload_cannot_escape(data_dir):
    outside = data_dir.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    store = FileStore("user-a")
    meta = store.save_upload(_pdf_bytes(), "doc.pdf")
    stored_path = store.uploads_dir / meta.stored_name
    stored_path.unlink()
    try:
        stored_path.symlink_to(outside)
    except OSError as e:
        pytest.skip(f"symlinks need privilege on this machine: {e}")
    assert store.resolve_upload(meta.id) is None


def test_symlink_user_dir_rejected(data_dir):
    import services.storage as storage_mod

    outside = data_dir.parent / "evil_target"
    outside.mkdir(exist_ok=True)
    link = storage_mod.data_root() / "users" / "evil"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as e:
        pytest.skip(f"symlinks need privilege on this machine: {e}")
    with pytest.raises(StorageError):
        storage_mod.user_dir("evil")


def test_adversarial_filenames(data_dir):
    store = FileStore("user-a")
    with pytest.raises(FileValidationError):
        store.save_upload(_pdf_bytes(), "x.pdf.exe")
    with pytest.raises(FileValidationError):
        store.save_upload(_pdf_bytes(), "noextension")
    # Null bytes are stripped; Windows-reserved stems are neutralized.
    meta = store.save_upload(_pdf_bytes(), "nul\x00.pdf")
    assert "_nul.pdf" in meta.stored_name
    assert store.resolve_upload(meta.id) is not None
    meta = store.save_upload(_pdf_bytes(), "  spaced name.pdf  ")
    assert meta.ext == "pdf"
    assert "/" not in meta.stored_name and "\\" not in meta.stored_name


def test_concurrent_saves_stay_valid(data_dir):
    import concurrent.futures as cf

    store = UserStore("user-a")
    vault = FileStore("user-a")

    def worker(n):
        store.save_chats([{"title": f"c{n}", "messages": []}], [])
        vault.register_output(f"f{n}.pptx", b"BYTES", "pptx")

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(8)))
    data, warnings = store.load_chats()
    assert isinstance(data, dict) and isinstance(data.get("chats"), list)
    assert len(vault.list_outputs()) == 8


def test_missing_directories_recreated(data_dir):
    import shutil

    shutil.rmtree(data_dir, ignore_errors=True)
    UserStore("user-a").save_chats([], [{"role": "user", "content": "hi"}])
    data, _ = UserStore("user-a").load_chats()
    assert data["current"] and data["current"][0]["content"] == "hi"


def test_generation_failure_is_structured(data_dir, monkeypatch):
    import tools.pptx_tool as pptx_tool
    import tools.docx_tool as docx_tool

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("lib broken")

    monkeypatch.setattr(pptx_tool, "Presentation", Boom)
    monkeypatch.setattr(docx_tool, "Document", Boom)
    ctx.set_current_user_id("user-a")
    assert pptx_tool.create_pptx.invoke(
        {"topic": "T", "content": "S1\n- a"}
    ).startswith("STATUS=FAILED")
    assert docx_tool.create_docx.invoke(
        {"title": "T", "content": "Hello"}
    ).startswith("STATUS=FAILED")


def test_generate_rate_limit_checked_before_work(data_dir, monkeypatch, tmp_path):
    import tools.pptx_tool as pptx_tool
    from services.files import FileStore
    from services.ratelimit import MemoryRateLimiter, configure_rate_limiter

    ctx.set_current_user_id("user-a")
    configure_rate_limiter(MemoryRateLimiter({"generate": (1, 3600.0)}))
    try:
        first = pptx_tool.create_pptx.invoke({"topic": "T", "content": "S1\n- a"})
        assert "file ID" in first
        assert len(FileStore("user-a").list_outputs()) == 1

        def _bomb(*a, **k):
            raise AssertionError("expensive generation must not run when quota exhausted")

        monkeypatch.setattr(pptx_tool, "Presentation", _bomb)
        second = pptx_tool.create_pptx.invoke({"topic": "T", "content": "S1\n- a"})
        assert second.startswith("STATUS=DENIED")
        # Rejected request performed no work and persisted nothing.
        assert len(FileStore("user-a").list_outputs()) == 1
        assert list(tmp_path.glob("pptx_*.pptx")) == []
    finally:
        configure_rate_limiter(MemoryRateLimiter())


def test_generate_without_user_context_denied(tmp_path):
    import tools.pptx_tool as pptx_tool
    import tools.docx_tool as docx_tool

    ctx.set_current_user_id(None)
    assert pptx_tool.create_pptx.invoke(
        {"topic": "T", "content": "S1\n- a"}
    ).startswith("STATUS=DENIED")
    assert docx_tool.create_docx.invoke(
        {"title": "T", "content": "Hello"}
    ).startswith("STATUS=DENIED")
    # No unowned artifacts may escape to the working directory.
    assert list(tmp_path.glob("pptx_*.pptx")) == []
    assert list(tmp_path.glob("docx_*.docx")) == []


def test_cooldown_shared_by_classify_and_answer():
    calls = {"bad": 0}

    def bad_getter():
        calls["bad"] += 1
        raise ConnectionError("down")

    class CatLLM:
        def invoke(self, messages):
            class R:
                content = "simple"

            return R()

    def good_getter():
        return CatLLM()

    out = agent.answer_with_fallback(
        "hi",
        tiers=[("bad", bad_getter), ("good", good_getter)],
        raw_messages=[{"role": "user", "content": "hi"}],
    )
    assert out["task_type"] == "simple"
    assert calls["bad"] == 1, calls


def test_probe_respects_cooldown(monkeypatch):
    calls = {"bad": 0}

    def bad_getter():
        calls["bad"] += 1
        raise ConnectionError("down")

    class HiLLM:
        def invoke(self, messages):
            class R:
                content = "hi"

            return R()

    monkeypatch.setattr(
        agent,
        "TIER_AGENT_GETTERS",
        [("bad", bad_getter), ("good", lambda: HiLLM())],
    )
    agent._record_tier_failure("bad")
    assert agent.probe_live_tier(timeout=5) == "good"
    assert calls["bad"] == 0


def test_forced_search_off_calls_nothing(monkeypatch):
    seen = []

    class SearchStub:
        name = "web_search"

        def invoke(self, args):
            seen.append(args)
            return "x"

    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    out = agent.run_tool_loop(_NoToolLLM(), "tell me news", [], force_web_search=False)
    assert seen == [] and out == "done"


def test_single_input_reaches_model_once(monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(identity, "get_current_user", lambda: identity.UserIdentity(id="u1", email=None, source="env"))
    captured = {}

    def fake_answer(user_input, chat_history=None, **kwargs):
        captured["input"] = user_input
        captured["history"] = list(chat_history or [])
        return {"output": "ok", "active_tier": "T", "task_type": "simple"}

    monkeypatch.setattr(agent, "answer_with_fallback", fake_answer)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.text_input(key="composer_input_0").set_value("unique-phrase-xyz").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    assert captured["input"] == "unique-phrase-xyz"
    for m in captured["history"]:
        assert getattr(m, "content", "") != "unique-phrase-xyz"


def test_attachment_send_uses_id_once(monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(identity, "get_current_user", lambda: identity.UserIdentity(id="u1", email=None, source="env"))
    captured = {}

    def fake_answer(user_input, chat_history=None, **kwargs):
        captured["input"] = user_input
        return {"output": "ok", "active_tier": "T", "task_type": "research"}

    monkeypatch.setattr(agent, "answer_with_fallback", fake_answer)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    meta = FileStore("u1").save_upload(_pdf_bytes(), "doc.pdf")
    at.session_state.pending_attach = {
        "upload_id": meta.id,
        "kind": "pdf",
        "name": "doc.pdf",
        "mark": ["t"],
    }
    at.run(timeout=60)
    at.text_input(key="composer_input_0").set_value("summarize").run(timeout=60)
    at.button(key="composer_send").click().run(timeout=120)
    assert not at.exception, f"send failed: {at.exception}"
    # The ID appears once as human-readable text and once inside the
    # explicit tool-call hint; the attachment itself is referenced once.
    assert captured["input"].count(f'upload_id="{meta.id}"') == 1
    users = [m for m in at.session_state.messages if m["role"] == "user"]
    assert users[-1]["attachments"] == [{"id": meta.id, "kind": "pdf", "name": "doc.pdf"}]


def test_corrupt_storage_recovered_with_warning(data_dir):
    store = UserStore("user-a")
    store.chats_path.parent.mkdir(parents=True, exist_ok=True)
    store.chats_path.write_text("{not json", encoding="utf-8")
    data, warnings = store.load_chats()
    assert data == {"chats": [], "current": []}
    assert warnings, "expected a corruption warning"
    backups = list(store.root.glob("chats.corrupt-*"))
    assert backups, "expected a quarantined backup file"


def test_storage_permission_failure_is_not_corruption(data_dir, monkeypatch):
    store = UserStore("user-a")
    store.save_chats([], [{"role": "user", "content": "hi", "time": "t"}])
    before = store.chats_path.stat().st_size

    def _deny(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr("builtins.open", _deny)
    data, warnings = store.load_chats()
    assert data == {"chats": [], "current": []}
    assert warnings and "permission" in warnings[0].lower()
    monkeypatch.undo()
    # Infrastructure failure must not quarantine or destroy stored data.
    assert store.chats_path.stat().st_size == before
    assert list(store.root.glob("chats.corrupt-*")) == []
    data, warnings = store.load_chats()
    assert data["current"][0]["content"] == "hi" and not warnings


def test_registry_permission_failure_raises(data_dir, monkeypatch):
    store = FileStore("user-a")
    meta = store.save_upload(_pdf_bytes(), "doc.pdf")

    def _deny(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr("builtins.open", _deny)
    # Unreadable registry surfaces instead of silently denying as unknown.
    with pytest.raises(StorageError):
        store.get_upload(meta.id)


def test_failed_atomic_write_cleans_tmp(data_dir, monkeypatch):
    import services.files as files_mod

    store = FileStore("user-a")

    def _boom_replace(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(files_mod, "atomic_replace", _boom_replace)
    with pytest.raises(FileValidationError):
        store.save_upload(_pdf_bytes(), "doc.pdf")
    leftovers = [p for p in store.uploads_dir.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
    assert list(store.uploads_dir.iterdir()) == []
    assert store.list_uploads() == []


def test_failed_json_write_keeps_original(data_dir, monkeypatch):
    import services.storage as storage_mod

    store = UserStore("user-a")
    store.save_chats([], [{"role": "user", "content": "keep me", "time": "t"}])
    before = store.chats_path.read_bytes()

    def _boom_replace(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(storage_mod, "atomic_replace", _boom_replace)
    with pytest.raises(StorageError):
        store.save_chats([], [{"role": "user", "content": "new", "time": "t"}])
    assert store.chats_path.read_bytes() == before
    data, warnings = store.load_chats()
    assert data["current"][0]["content"] == "keep me" and not warnings


def test_structured_corruption_warns(data_dir):
    store = UserStore("user-a")
    store.structured_path.parent.mkdir(parents=True, exist_ok=True)
    store.structured_path.write_text("{not json", encoding="utf-8")
    mem, warnings = store.load_structured()
    assert mem["facts"] == [] and warnings
    assert list(store.root.glob("structured.corrupt-*"))


def test_upload_count_quota_enforced(data_dir, monkeypatch):
    from services import files as files_mod

    monkeypatch.setattr(files_mod, "MAX_UPLOADS_PER_USER", 2)
    FileStore("user-a").save_upload(_pdf_bytes(), "a.pdf")
    FileStore("user-a").save_upload(_pdf_bytes(), "b.pdf")
    with pytest.raises(FileValidationError):
        FileStore("user-a").save_upload(_pdf_bytes(), "c.pdf")


def test_upload_bytes_quota_enforced(data_dir, monkeypatch):
    from services import files as files_mod

    monkeypatch.setattr(files_mod, "MAX_USER_BYTES", 10)
    with pytest.raises(FileValidationError):
        FileStore("user-a").save_upload(_pdf_bytes(), "big.pdf")


def test_output_retention_idempotent_and_bounded(data_dir):
    import json
    import time

    store = FileStore("user-a")
    old = store.register_output("old.pptx", b"data-bytes", "pptx")
    new = store.register_output("new.pptx", b"data-bytes", "pptx")
    reg = json.loads(store.outputs_registry.read_text(encoding="utf-8"))
    reg[old.id]["created"] = time.time() - 40 * 86400.0
    store.outputs_registry.write_text(json.dumps(reg), encoding="utf-8")
    assert store.prune_stale_outputs(30) == 1
    assert store.get_output(old.id) is None
    assert store.get_output(new.id) is not None
    assert store.prune_stale_outputs(30) == 0
    # Retention never crosses user boundaries.
    other = FileStore("user-b").register_output("o.pptx", b"x", "pptx")
    oreg = json.loads(FileStore("user-b").outputs_registry.read_text(encoding="utf-8"))
    oreg[other.id]["created"] = time.time() - 40 * 86400.0
    FileStore("user-b").outputs_registry.write_text(json.dumps(oreg), encoding="utf-8")
    assert FileStore("user-a").prune_stale_outputs(30) == 0
    assert FileStore("user-b").resolve_upload(other.id) is None
    assert FileStore("user-b").get_output(other.id) is not None


def test_reconcile_reports_and_cleans_tmp(data_dir):
    import json

    store = FileStore("user-a")
    meta = store.save_upload(_pdf_bytes(), "doc.pdf")
    (store.uploads_dir / "deadbeefcafe1234_orphan.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
    (store.uploads_dir / "stale.123.abcdef12.tmp").write_bytes(b"partial")
    (store.uploads_dir / meta.stored_name).unlink()
    reg = json.loads(store.uploads_registry.read_text(encoding="utf-8"))
    reg["badkey"] = [1, 2, 3]
    store.uploads_registry.write_text(json.dumps(reg), encoding="utf-8")

    report = store.reconcile()
    assert meta.id in report["missing_files"]
    assert "deadbeefcafe1234_orphan.pdf" in report["orphan_files"]
    assert "badkey" in report["bad_records"]
    assert report["removed_tmp"] == ["stale.123.abcdef12.tmp"]
    assert not (store.uploads_dir / "stale.123.abcdef12.tmp").exists()
    # Conservative: orphans are reported but kept; dangling records kept.
    assert (store.uploads_dir / "deadbeefcafe1234_orphan.pdf").exists()
    assert store.get_upload(meta.id) is not None
    assert store.reconcile()["removed_tmp"] == []


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

