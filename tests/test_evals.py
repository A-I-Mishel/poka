"""Lite eval harness: golden tasks with property scoring (Milestone 1b).

Twelve tasks (4 research / 4 data / 4 creative-multi-step) run against
scripted FakeLLMs with REAL tools (uploads, CSV, logic, SQLite vault) —
zero model quota in CI. Properties assert orchestration contracts, not
model eloquence: provenance recorded, no STATUS markers leaked into
final text, no tracebacks, tool attribution truthful.

Live-tier runs are opt-in (PLUTO_EVAL_LIVE=1, weekly/pre-deploy): the
same properties against the real cascade. Skipped otherwise, and skipped
when no live tier answers.
"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from services import context as ctx
from services.files import FileStore


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "eval-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("eval-user")
    ctx.set_limit_key("eval-user")
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)


@pytest.fixture(autouse=True)
def _clean_agent_state():
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
    agent._clear_summary_cache()
    yield
    agent._TIER_FAILS.clear()
    agent._TIER_SKIP_UNTIL.clear()
    agent._TIER_TIMEOUTS.clear()
    agent._clear_summary_cache()


class FakeLLM:
    """Scripted stand-in: items are text or (text, tool_calls)."""

    def __init__(self, script):
        self.script = list(script)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if self.script:
            item = self.script.pop(0)
            text, calls = item if isinstance(item, tuple) else (item, [])
        else:
            text, calls = ("ok", [])
        return SimpleNamespace(content=text, tool_calls=calls)


def _tiers(fake):
    return [("fake", lambda: fake)]


def _call(name, args):
    return {"name": name, "args": args, "id": "call-1"}


def _upload(text, name="note.txt"):
    return FileStore("eval-user").save_upload(text.encode("utf-8"), name)


def _check_common(out):
    """Properties every answer must satisfy."""
    failures = []
    text = str(out.get("output", "") or "")
    if not text.strip():
        failures.append("empty output")
    if "STATUS=FAILED" in text:
        failures.append("leaked STATUS=FAILED marker")
    if "Traceback" in text:
        failures.append("leaked traceback")
    return failures


# --- research ----------------------------------------------------


def test_eval_r1_document_qa(env):
    meta = _upload("Quarterly revenue rose 12 percent on cloud growth.")
    fake = FakeLLM([
        ("", [_call("read_document", {"upload_id": meta.id})]),
        ("Revenue rose 12 percent on cloud growth.", []),
    ])
    out = agent.answer_with_fallback(
        "What does the note say about revenue?", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if "revenue" not in out["output"].lower():
        failures.append("answer ignores tool content")
    if out.get("tools_used") != ["read_document"]:
        failures.append(f"bad tools_used: {out.get('tools_used')}")
    assert not failures, failures


def test_eval_r2_search_provenance(env, monkeypatch):
    class SearchStub:
        name = "web_search"

        def invoke(self, args):
            return ("[1] Example Title — example.com\n"
                    "URL: https://example.com/page\n"
                    "Example details snippet.")

    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    fake = FakeLLM([
        ("", [_call("web_search", {"query": "example topic"})]),
        ("Per Example Title, details are at the linked page.", []),
    ])
    out = agent.answer_with_fallback(
        "latest news on example topic", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if "web_search" not in (out.get("tools_used") or []):
        failures.append("search not recorded")
    if not out.get("sources"):
        failures.append("executed search yielded no sources")
    assert not failures, failures


def test_eval_r3_teaching_without_files(env):
    fake = FakeLLM(["Please upload the lecture slides first."])
    out = agent.answer_with_fallback(
        "teach me these slides one by one", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    assert not failures, failures


def test_eval_r4_empty_file_hygiene(env):
    meta = _upload("   ")
    fake = FakeLLM([
        ("", [_call("read_document", {"upload_id": meta.id})]),
        ("The file has no readable text to teach from.", []),
    ])
    out = agent.answer_with_fallback(
        "summarize this document", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if out.get("tools_used") != ["read_document"]:
        failures.append(f"bad tools_used: {out.get('tools_used')}")
    assert not failures, failures


# --- data --------------------------------------------------------


def test_eval_d1_csv_analysis(env):
    meta = FileStore("eval-user").save_upload(
        b"name,age\namy,30\nbob,25\n", "ages.csv")
    fake = FakeLLM([
        ("", [_call("analyze_csv", {"upload_id": meta.id})]),
        ("The file has 2 rows over 2 columns.", []),
    ])
    out = agent.answer_with_fallback(
        "analyze this csv", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if out.get("tools_used") != ["analyze_csv"]:
        failures.append(f"bad tools_used: {out.get('tools_used')}")
    assert not failures, failures


def test_eval_d2_logic_check(env):
    fake = FakeLLM([
        ("", [_call("check_logic", {"operation": "valid",
                                   "premises": "p -> q\np", "conclusion": "q"})]),
        ("The argument is valid by modus ponens.", []),
    ])
    out = agent.answer_with_fallback(
        "is this argument valid", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if out.get("tools_used") != ["check_logic"]:
        failures.append(f"bad tools_used: {out.get('tools_used')}")
    assert not failures, failures


def test_eval_d3_failed_tool_hygiene(env):
    fake = FakeLLM([
        ("", [_call("query_database", {"sql": "SELECT * FROM missing"})]),
        ("That table does not exist in your vault.", []),
    ])
    out = agent.answer_with_fallback(
        "analyze the dataset in the missing table", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if out.get("tools_used") != ["query_database"]:
        failures.append(f"bad tools_used: {out.get('tools_used')}")
    assert not failures, failures


def test_eval_d4_two_reads_combine(env):
    first = _upload("alpha marker", name="a.txt")
    second = _upload("beta marker", name="b.txt")
    fake = FakeLLM([
        ("", [_call("read_document", {"upload_id": first.id})]),
        ("", [_call("read_document", {"upload_id": second.id})]),
        ("Alpha and beta markers found across both files.", []),
    ])
    out = agent.answer_with_fallback(
        "read and summarize these two documents", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    text = out["output"].lower()
    if "alpha" not in text or "beta" not in text:
        failures.append("final ignores collected tool results")
    assert not failures, failures


# --- creative / multi-step ---------------------------------------


def test_eval_c1_simple_greeting(env):
    fake = FakeLLM(["hello back"])
    out = agent.answer_with_fallback("hello", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if out.get("task_type") != "simple":
        failures.append(f"wrong task_type: {out.get('task_type')}")
    if out.get("tools_used"):
        failures.append("simple answer used tools")
    assert not failures, failures


def test_eval_c2_invalid_spec_hygiene(env):
    fake = FakeLLM([
        ("", [_call("build_presentation", {"spec_json": "not-json"})]),
        ("That spec was not valid JSON; here is what I need instead.", []),
    ])
    out = agent.answer_with_fallback(
        "make a presentation", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if out.get("tools_used") != ["build_presentation"]:
        failures.append(f"bad tools_used: {out.get('tools_used')}")
    assert not failures, failures


def test_eval_c3_research_plus_logic(env, monkeypatch):
    class SearchStub:
        name = "web_search"

        def invoke(self, args):
            return ("[1] Logic Guide — example.com\n"
                    "URL: https://example.com/logic\n"
                    "Modus ponens rules snippet.")

    monkeypatch.setitem(agent.TOOL_MAP, "web_search", SearchStub())
    fake = FakeLLM([
        ("", [_call("web_search", {"query": "modus ponens"})]),
        ("", [_call("check_logic", {"operation": "valid",
                                   "premises": "p -> q\np", "conclusion": "q"})]),
        ("Modus ponens checks out as valid.", []),
    ])
    out = agent.answer_with_fallback(
        "search modus ponens and verify it", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if out.get("tools_used") != ["web_search", "check_logic"]:
        failures.append(f"bad tools_used: {out.get('tools_used')}")
    assert not failures, failures


def test_eval_c4_unknown_tool_call_ignored(env):
    fake = FakeLLM([
        ("thinking", [{"name": "bogus-tool-xyz", "args": {}, "id": "9"}]),
        ("Done without that tool.", []),
    ])
    out = agent.answer_with_fallback(
        "do the thing", tiers=_tiers(fake), raw_messages=[])
    failures = _check_common(out)
    if "bogus-tool-xyz" in (out.get("tools_used") or []):
        failures.append("unknown tool recorded")
    assert not failures, failures


# --- live (opt-in) ------------------------------------------------


@pytest.mark.skipif(os.getenv("PLUTO_EVAL_LIVE") != "1",
                    reason="live evals are opt-in (quota-bearing)")
def test_eval_live_smoke(env):
    live_inputs = ["hello", "what is 2+2", "summarize: the sky is blue"]
    for text in live_inputs:
        try:
            out = agent.answer_with_fallback(text, raw_messages=[])
        except RuntimeError as e:
            pytest.skip(f"no live tier answered: {e}")
        assert str(out.get("output", "") or "").strip(), text
        assert "Traceback" not in str(out.get("output", ""))
