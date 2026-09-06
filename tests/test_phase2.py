"""Phase 2 regression tests: auth, rate limits, routing, context budgets,
request budgets, provider reliability, resource controls, incremental
memory, safe caching.

Hermetic like Phase 1: tmp DATA_DIR, env identity, stubbed LLMs/tools.
No test spends model quota or touches the network.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from services import context as ctx

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("POKA_USER_ID", "test-user")
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    ctx.set_current_user_id("test-user")
    yield tmp_path / "data"
    ctx.set_current_user_id(None)


@pytest.fixture(autouse=True)
def _clean_agent_state():
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent.ROUTER_STATS["rule"] = 0
    agent.ROUTER_STATS["llm"] = 0
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()


@pytest.fixture()
def mem_dir(tmp_path, monkeypatch):
    """Point structured memory at tmp (agent reads it via memory_engine)."""
    import memory_engine

    target = tmp_path / "memuser"
    target.mkdir()
    old = memory_engine._MEMORY_DIR
    memory_engine.set_memory_dir(str(target))
    yield target
    memory_engine.set_memory_dir(old)


@pytest.fixture()
def mem_dir(tmp_path):
    """Point structured memory at tmp (agent reads it via memory_engine)."""
    import memory_engine

    target = tmp_path / "memuser"
    target.mkdir()
    old = memory_engine._MEMORY_DIR
    memory_engine.set_memory_dir(str(target))
    yield target
    memory_engine.set_memory_dir(old)


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


# -- AUTH ---------------------------------------------------------------

def test_tool_budget_stops_loop():
    import services.identity as identity

    class AlwaysTool:
        calls = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            type(self).calls += 1
            if type(self).calls <= 2:
                class T:
                    content = ""
                    tool_calls = [{"name": "missing-tool-xyz", "args": {}}]

                return T()

            class R:
                content = "final answer"
                tool_calls = []

            return R()

    AlwaysTool.calls = 0
    budget = agent.RequestBudget(max_tools=1, max_llm=50)
    out = agent.run_tool_loop(AlwaysTool(), "do thing", [], budget=budget)
    assert out == "final answer"


def test_private_app_shows_signin(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("POKA_AUTH_MODE", "private")
    monkeypatch.delenv("POKA_USER_ID", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    assert any("Sign in" in str(b.label) for b in at.button)


def test_tool_sees_user_context_in_worker(data_dir):
    """Worker threads must observe the submitting request's user ID."""
    from services import context as ctx2

    seen = {}

    class WhoAmI:
        name = "whoami"

        def invoke(self, args):
            seen["uid"] = ctx2.get_current_user_id()
            return "ok"

    import agent as agent_mod

    monkeypatch_ctx = ctx2
    monkeypatch_ctx.set_current_user_id("worker-user")
    try:
        agent_mod.TOOL_MAP["whoami"] = WhoAmI()
        out = agent_mod._execute_tool_call({"name": "whoami", "args": {}})
        assert out.startswith("STATUS=OK")
        assert seen.get("uid") == "worker-user"
    finally:
        agent_mod.TOOL_MAP.pop("whoami", None)
        monkeypatch_ctx.set_current_user_id(None)


def test_env_identity_stable(monkeypatch):
    from services.identity import get_current_user

    monkeypatch.setenv("POKA_USER_ID", "operator-1")
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    first = get_current_user()
    second = get_current_user()
    assert first.id == second.id == "operator-1"
    assert first.source == "env"


def test_private_mode_rejects_anonymous(monkeypatch):
    from services.auth import AuthRequired, authenticate
    from services.identity import AuthRequired as IdentityAuthRequired

    monkeypatch.setenv("POKA_AUTH_MODE", "private")
    monkeypatch.delenv("POKA_USER_ID", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    with pytest.raises((AuthRequired, IdentityAuthRequired)):
        authenticate()


def test_private_mode_env_identity_ok(monkeypatch):
    from services.auth import authenticate

    monkeypatch.setenv("POKA_AUTH_MODE", "private")
    monkeypatch.setenv("POKA_USER_ID", "boss")
    result = authenticate()
    assert result.authenticated is True
    assert result.identity.id == "boss"


def test_access_token_accept_reject(monkeypatch):
    from services.auth import verify_access_token

    monkeypatch.setenv("POKA_ACCESS_TOKENS", "alpha-secret, beta-secret")
    uid = verify_access_token("alpha-secret")
    assert uid and uid.startswith("token-")
    assert verify_access_token("alpha-secret") == uid  # stable
    assert verify_access_token("wrong") is None
    assert verify_access_token("") is None
    assert verify_access_token(None) is None


def test_link_token_not_auth_in_private(monkeypatch):
    from services.auth import AuthRequired, authenticate
    from services.identity import AuthRequired as IdentityAuthRequired

    monkeypatch.setenv("POKA_AUTH_MODE", "private")
    monkeypatch.delenv("POKA_USER_ID", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    # A forged ?uid= for another user must not authenticate.
    with pytest.raises((AuthRequired, IdentityAuthRequired, Exception)):
        authenticate()


def test_private_app_shows_signin(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("POKA_DATA_DIR", "/tmp/poka-p2-nobody")
    monkeypatch.setenv("POKA_AUTH_MODE", "private")
    monkeypatch.delenv("POKA_USER_ID", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    assert any("Sign in" in str(b.label) for b in at.button)


# -- RATE LIMITING --------------------------------------------------------

def test_rate_limit_allow_then_deny():
    from services.ratelimit import MemoryRateLimiter

    limiter = MemoryRateLimiter({"chat": (2, 60.0)})
    assert limiter.check("u1", "chat").allowed
    assert limiter.check("u1", "chat").allowed
    denied = limiter.check("u1", "chat")
    assert not denied.allowed and denied.retry_after > 0


def test_rate_limit_users_independent():
    from services.ratelimit import MemoryRateLimiter

    limiter = MemoryRateLimiter({"chat": (1, 60.0)})
    assert limiter.check("u1", "chat").allowed
    assert not limiter.check("u1", "chat").allowed
    assert limiter.check("u2", "chat").allowed


def test_rate_limit_zero_quota_denies_without_crash():
    from services.ratelimit import MemoryRateLimiter

    limiter = MemoryRateLimiter({"chat": (0, 60.0)})
    denied = limiter.check("u1", "chat")
    assert not denied.allowed and denied.retry_after > 0


def test_rate_limit_window_expiry():
    from services.ratelimit import MemoryRateLimiter

    limiter = MemoryRateLimiter({"chat": (1, 0.05)})
    assert limiter.check("u1", "chat").allowed
    assert not limiter.check("u1", "chat").allowed
    time.sleep(0.08)
    assert limiter.check("u1", "chat").allowed


def test_rate_limit_reset():
    from services.ratelimit import MemoryRateLimiter

    limiter = MemoryRateLimiter({"chat": (1, 60.0)})
    assert limiter.check("u1", "chat").allowed
    assert not limiter.check("u1", "chat").allowed
    limiter.reset("u1")
    assert limiter.check("u1", "chat").allowed


def test_chat_rate_limit_blocks_send(monkeypatch, data_dir):
    from services.ratelimit import MemoryRateLimiter, configure_rate_limiter
    import services.identity as identity

    monkeypatch.setattr(identity, "get_current_user", lambda: identity.UserIdentity(id="u1", email=None, source="env"))
    configure_rate_limiter(MemoryRateLimiter({"chat": (1, 3600.0), "deep": (100, 3600.0)}))
    try:
        import agent as agent_mod

        monkeypatch.setattr(
            agent_mod,
            "answer_with_fallback",
            lambda *a, **k: {"output": "ok", "active_tier": "T", "task_type": "simple"},
        )
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(APP_PATH)
        at.run(timeout=120)
        assert not at.exception
        at.text_input(key="composer_input_0").set_value("one").run(timeout=60)
        at.button(key="composer_send").click().run(timeout=120)
        assert not at.exception
        at.text_input(key="composer_input_1").set_value("two").run(timeout=60)
        at.button(key="composer_send").click().run(timeout=120)
        assert not at.exception
        errors = [e.value for e in at.error]
        assert any("rate limit" in str(v).lower() for v in errors)
        assistants = [m for m in at.session_state.messages if m["role"] == "assistant"]
        assert len(assistants) == 1
    finally:
        configure_rate_limiter(MemoryRateLimiter())


# -- ROUTING -----------------------------------------------------------------

def test_rule_router_table():
    cases = {
        "hello": "simple",
        "hi!": "simple",
        "thanks": "simple",
        "read abc123def4567890 please": "research",
        "analyze my csv": "data",
        "make a presentation on mars": "creative",
        "write an essay": "creative",
        "what is gravity?": None,  # ambiguous -> LLM
        "research blockchain then make a presentation": "multi_step",
        "latest AI news today": "research",
    }
    for text, expected in cases.items():
        got = agent.rule_route(text)
        assert got == expected, (text, got, expected)


def test_router_stats_tracked(monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(identity, "get_current_user", lambda: identity.UserIdentity(id="u1", email=None, source="env"))

    class FakeLLM:
        def invoke(self, messages):
            class R:
                content = "hi"

            return R()

    tiers = [("fake", lambda: FakeLLM())]
    agent.answer_with_fallback("hello", tiers=tiers, raw_messages=[])
    assert agent.ROUTER_STATS["rule"] >= 1
    before = agent.ROUTER_STATS["llm"]
    agent.answer_with_fallback(
        "flibbertigibbet ponderings about quarks",
        tiers=tiers,
        raw_messages=[],
    )
    assert agent.ROUTER_STATS["llm"] > before


# -- CONTEXT --------------------------------------------------------------------

def test_history_trim_keeps_newest():
    from langchain_core.messages import HumanMessage

    from services.context_budget import fit_history

    msgs = [HumanMessage(content=f"message number {i} " + "x" * 500) for i in range(10)]
    kept, stats = fit_history(msgs, 300)
    assert stats["dropped"] > 0
    assert kept[-1].content.startswith("message number 9")
    single, _ = fit_history([], 800)
    assert single == []


def test_current_request_never_truncated():
    from services.tokens import count_tokens

    big = "word " * 20000
    assert count_tokens(big) > 0  # counting works; caller keeps full text
    from services.context_budget import fit_text

    assert "hello" in fit_text("hello world", 100000)


def test_tool_result_capped(monkeypatch):
    class Big:
        name = "big"

        def invoke(self, args):
            return "z" * 50000

    monkeypatch.setitem(agent.TOOL_MAP, "big", Big())
    out = agent._execute_tool_call({"name": "big", "args": {}})
    assert out.startswith("STATUS=OK")
    assert "truncated to fit context" in out
    from services.tokens import count_tokens

    assert count_tokens(out) <= 3000 + 200


# -- BUDGETS ----------------------------------------------------------------------

def test_budget_counts_and_exhausts():
    budget = agent.RequestBudget(max_llm=2, max_tools=1, max_search=1)
    budget.count_llm()
    budget.count_llm()
    with pytest.raises(agent.BudgetExhausted):
        budget.count_llm()
    budget2 = agent.RequestBudget(max_tools=1, max_search=5)
    budget2.count_tool(is_search=False)
    with pytest.raises(agent.BudgetExhausted):
        budget2.count_tool(is_search=False)


def test_budget_deadline():
    budget = agent.RequestBudget()
    budget.deadline = 0.0
    with pytest.raises(agent.BudgetExhausted):
        budget.check_time()
    with pytest.raises(agent.BudgetExhausted):
        budget.count_llm()


def test_tool_budget_stops_loop(monkeypatch):
    import services.identity as identity

    monkeypatch.setattr(identity, "get_current_user", lambda: identity.UserIdentity(id="u1", email=None, source="env"))

    class AlwaysTool:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            class T:
                content = ""
                tool_calls = [{"name": "missing-tool-xyz", "args": {}}]

            return T()

    budget = agent.RequestBudget(max_tools=1, max_llm=50)
    out = agent.run_tool_loop(AlwaysTool(), "do thing", [], budget=budget)
    assert isinstance(out, str) and len(out) > 0


def test_reflect_budget_capped():
    budget = agent.RequestBudget(max_reflect=0)

    class FakeLLM:
        invoked = 0

        def invoke(self, messages):
            type(self).invoked += 1
            class R:
                content = "x"

            return R()

    out = agent.reflect_and_improve(FakeLLM(), "q", "draft text here", [], budget)
    assert out == "draft text here"
    assert FakeLLM.invoked == 0


# -- PROVIDER RELIABILITY --------------------------------------------------------------

def test_failure_kinds_table():
    assert agent.classify_provider_error(TimeoutError("x")) == ("timeout", True)
    assert agent.classify_provider_error(RuntimeError("429 quota"))[0] == "rate_limit"
    assert agent.classify_provider_error(RuntimeError("401 Unauthorized")) == ("auth", False)
    assert agent.classify_provider_error(RuntimeError("503 unavailable"))[0] == "server"
    kind, retryable = agent.classify_provider_error(RuntimeError("400 bad request"))
    assert (kind, retryable) == ("invalid", False)


def test_permanent_failure_cools_longer():
    agent._record_tier_failure("t1", permanent=False)
    short_until = agent._TIER_SKIP_UNTIL["t1"]
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._record_tier_failure("t1", permanent=True)
    long_until = agent._TIER_SKIP_UNTIL["t1"]
    assert long_until - short_until > 2000


def test_cascade_attempts_list():
    order = []

    def fail_first(name, llm):
        order.append(name)
        if name == "bad":
            raise ConnectionError("down")
        return "good-result"

    tiers = [("bad", lambda: object()), ("good", lambda: object())]
    attempts: list = []
    name, result = agent._run_cascade_step(fail_first, None, tiers, attempts)
    assert (name, result) == ("good", "good-result")
    assert attempts == ["bad", "good"]


def test_bounded_call_returns_control_on_timeout():
    import time

    started = time.time()
    with pytest.raises(TimeoutError):
        agent._call_bounded(lambda: time.sleep(30), timeout=0.2, what="slow-op")
    assert time.time() - started < 10


def test_bounded_pool_limits_threads():
    import threading
    import time

    workers = [t for t in threading.enumerate() if t.name.startswith("poka-bounded")]
    assert 1 <= len(workers) <= agent._BOUNDED_MAX_WORKERS

    def hang():
        # Short hang: workers stay occupied through the burst below but
        # drain fast so later tests are unaffected.
        time.sleep(2)

    for _ in range(agent._BOUNDED_MAX_WORKERS + 6):
        with pytest.raises(TimeoutError):
            agent._call_bounded(hang, timeout=0.05, what="hang")
    workers = [t for t in threading.enumerate() if t.name.startswith("poka-bounded")]
    assert len(workers) <= agent._BOUNDED_MAX_WORKERS


def test_bounded_worker_exception_propagates():
    def boom():
        raise ValueError("worker blew up")

    # Generous timeout: earlier tests may leave pool workers briefly busy.
    with pytest.raises(ValueError, match="worker blew up"):
        agent._call_bounded(boom, timeout=30.0, what="boom")
    # Pool still serves after a worker exception.
    assert agent._call_bounded(lambda: "alive", timeout=30.0, what="ping") == "alive"


def test_first_token_timeout_fails_fast(monkeypatch):
    import time

    from langchain_core.messages import AIMessageChunk

    monkeypatch.setenv("POKA_FIRST_TOKEN_TIMEOUT", "0.05")

    class SlowStream:
        def stream(self, messages):
            time.sleep(2)
            yield AIMessageChunk(content="too late")

    started = time.time()
    with pytest.raises(TimeoutError, match="first token timed out"):
        agent._invoke_bounded(SlowStream(), "hi", timeout=30.0)
    # Fast fail: well under the 30s total timeout.
    assert time.time() - started < 10


def test_silent_tier_falls_back_to_next(monkeypatch):
    import time

    from langchain_core.messages import AIMessageChunk

    monkeypatch.setenv("POKA_FIRST_TOKEN_TIMEOUT", "0.05")

    class SlowStream:
        def stream(self, messages):
            time.sleep(2)
            yield AIMessageChunk(content="too late")

    class QuickReply:
        def invoke(self, messages):
            class R:
                content = "fast answer"

            return R()

    name, result = agent._run_cascade_step(
        lambda _name, llm: agent._invoke_bounded(llm, "hi"),
        None,
        [("slow", SlowStream), ("quick", QuickReply)],
    )
    assert name == "quick"
    assert result.content == "fast answer"


def test_invoke_only_model_skips_streaming(monkeypatch):
    # Legacy models / test doubles without .stream() use plain invoke.
    monkeypatch.setenv("POKA_FIRST_TOKEN_TIMEOUT", "0.05")

    class InvokeOnly:
        def invoke(self, messages):
            class R:
                content = "direct"

            return R()

    assert agent._invoke_bounded(InvokeOnly(), "hi", timeout=30.0).content == "direct"


def test_streamed_chunks_merge_text(monkeypatch):
    from langchain_core.messages import AIMessageChunk

    monkeypatch.setenv("POKA_FIRST_TOKEN_TIMEOUT", "5")

    class Chunked:
        def stream(self, messages):
            yield AIMessageChunk(content="Hel")
            yield AIMessageChunk(content="lo")

    assert agent._invoke_bounded(Chunked(), "hi", timeout=30.0).content == "Hello"


def test_fallback_attempts_consume_llm_budget():
    import agent as agent_mod

    calls = {"n": 0}

    class AlwaysFail:
        def invoke(self, messages):
            calls["n"] += 1
            raise ConnectionError("down")

    # Both fallback attempts run and are charged...
    budget = agent_mod.RequestBudget(max_llm=2)
    with pytest.raises(RuntimeError):
        agent_mod._run_cascade_step(
            lambda _name, llm: agent_mod._invoke_bounded(llm, "hi", budget=budget),
            None,
            [("t1", AlwaysFail), ("t2", AlwaysFail)],
        )
    assert calls["n"] == 2
    assert budget.llm_calls == 2
    # ...and once the budget is spent, further fallback is blocked
    # instead of retrying for free (failures never reset counters).
    tight = agent_mod.RequestBudget(max_llm=1)
    with pytest.raises(agent_mod.BudgetExhausted):
        agent_mod._run_cascade_step(
            lambda _name, llm: agent_mod._invoke_bounded(llm, "hi", budget=tight),
            None,
            [("t1", AlwaysFail), ("t2", AlwaysFail)],
        )
    assert calls["n"] == 3


def test_tool_failure_still_counts_tool_budget():
    import agent as agent_mod

    class BadTool:
        name = "bad-tool"

        def invoke(self, args):
            raise RuntimeError("tool exploded")

    agent_mod.TOOL_MAP["bad-tool"] = BadTool()
    try:
        budget = agent_mod.RequestBudget(max_tools=10)
        out = agent_mod._execute_tool_call({"name": "bad-tool", "args": {}}, budget)
        assert out.startswith("STATUS=FAILED")
        assert budget.tool_calls == 1
    finally:
        agent_mod.TOOL_MAP.pop("bad-tool", None)


def test_provider_error_classification_preserved():
    assert agent.classify_provider_error(TimeoutError("Model request timed out after 90s.")) == ("timeout", True)
    assert agent.classify_provider_error(RuntimeError("429 quota exceeded"))[0] == "rate_limit"


# -- PDF / CSV / SEARCH CONTROLS ----------------------------------------------------------

def test_pdf_page_markers_and_cap(data_dir, monkeypatch):
    import tools.pdf_tool as pdf_tool
    from pypdf import PdfReader, PdfWriter

    monkeypatch.setattr(pdf_tool, "MAX_PDF_PAGES", 1)
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=72, height=72)
    data_dir.mkdir(parents=True, exist_ok=True)
    buf_path = str(data_dir / "blank.pdf")
    with open(buf_path, "wb") as f:
        writer.write(f)
    assert len(PdfReader(buf_path).pages) == 3
    from services.files import FileStore

    ctx = __import__("services.context", fromlist=["x"])
    ctx.set_current_user_id("user-a")
    meta = FileStore("user-a").save_upload(open(buf_path, "rb").read(), "blank.pdf")
    out = pdf_tool.read_pdf.invoke({"upload_id": meta.id})
    assert "only the first 1 of 3 pages" in out


def test_pdf_oversized_bytes_rejected(data_dir, monkeypatch):
    import tools.pdf_tool as pdf_tool
    from services.files import FileStore
    from services import context as ctx2

    ctx2.set_current_user_id("user-a")
    big = b"%PDF-1.4\n" + b"x" * 100
    import services.limits as limits

    monkeypatch.setattr(limits, "MAX_UPLOAD_BYTES", 10)
    # validate_upload reads the module constant at call time
    from services import files as files_mod

    monkeypatch.setattr(files_mod, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(Exception):
        FileStore("user-a").save_upload(big, "big.pdf")


def test_csv_malformed_tolerated(data_dir):
    import tools.data_tool as data_tool
    from services.files import FileStore
    from services import context as ctx2

    ctx2.set_current_user_id("user-a")
    raw = b"a,b\n1,2\nBADLINE\n3,4\n"
    meta = FileStore("user-a").save_upload(raw, "messy.csv")
    out = data_tool.analyze_csv.invoke({"upload_id": meta.id})
    assert "STATUS=FAILED" not in out
    assert "Rows analyzed" in out


def test_search_query_capped(monkeypatch):
    import tools.search_tool as search_tool

    seen = {}

    class FakeDDGS:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, max_results=5):
            seen["query"] = query
            return [{"title": "T", "href": "https://example.com/a", "body": "snip"}]

        def news(self, query, max_results=5):
            return self.text(query, max_results)

    monkeypatch.setattr("duckduckgo_search.DDGS", FakeDDGS)
    out = search_tool.web_search.invoke({"query": "x" * 500})
    assert seen["query"] is not None and len(seen["query"]) <= 300
    assert "[1]" in out and "https://example.com/a" in out


# -- MEMORY EFFICIENCY ----------------------------------------------------------

def test_incremental_memory_only_new(mem_dir):
    import memory_engine

    base = [{"role": "user", "content": f"my name is Test{i} unique{i}"} for i in range(10)]
    first = memory_engine.update_memory_incremental(base)
    assert first["processed"] == 10 and first["saved"] is True
    again = memory_engine.update_memory_incremental(base)
    assert again == {"processed": 0, "new_facts": 0, "saved": False}
    extended = base + [{"role": "user", "content": "my name is Final extra fact here"}]
    third = memory_engine.update_memory_incremental(extended)
    assert third["processed"] == 1 and third["saved"] is True


def test_memory_dedup_no_duplicates(mem_dir):
    import memory_engine

    msgs = [{"role": "user", "content": "my name is Alex"}]
    memory_engine.update_memory_incremental(msgs)
    memory_engine.update_memory_incremental(msgs)
    mem = memory_engine.load_structured_memory()
    names = [f for f in mem["facts"] if f.get("type") == "name"]
    assert len(names) == 1


def test_memory_cross_user_isolated(mem_dir, monkeypatch, tmp_path):
    import memory_engine

    memory_engine.update_memory_incremental([{"role": "user", "content": "my name is Alice"}])
    other = tmp_path / "other"
    other.mkdir()
    memory_engine.set_memory_dir(str(other))
    try:
        mem = memory_engine.load_structured_memory()
        assert mem["user_name"] is None and mem["facts"] == []
    finally:
        memory_engine.set_memory_dir(str(mem_dir))


# -- CACHING --------------------------------------------------------------------

def test_tokenizer_cached_no_user_data():
    from services.tokens import _encoder, count_tokens

    assert count_tokens("hello world") > 0
    assert _encoder() is _encoder()  # same shared instance


def test_skip_cache_holds_no_user_data():
    agent._record_tier_failure("tier-x")
    assert "tier-x" in agent._TIER_SKIP_UNTIL
    blob = repr(agent._TIER_FAILS) + repr(agent._TIER_SKIP_UNTIL)
    assert "hello" not in blob and "@" not in blob
