"""Workflow tests: validation, vault storage, deterministic runner, API.

Offline throughout: a fake echo tool stands in for network tools via
TOOL_MAP injection (auto-reverted), and private-mode-only tools are
never needed here.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.tools import tool

from agent.budget import RequestBudget
from agent.toolrun import TOOL_MAP
from agent.workflows import run_workflow
from services import context as ctx
from services import workflows as wf_svc
from services.storage import UserStore


@tool
def _wf_echo(text: str = "") -> str:
    """Test echo tool (never shipped)."""
    if text == "boom":
        return "STATUS=FAILED tool=_wf_echo: boom"
    return f"echo:{text}"


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "wf-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    ctx.set_current_user_id("wf-user")
    ctx.set_limit_key("wf-user")
    monkeypatch.setitem(TOOL_MAP, "_wf_echo", _wf_echo)
    from services import ratelimit as rl

    old = rl.get_rate_limiter()
    rl.configure_rate_limiter(rl.MemoryRateLimiter())
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)
    rl.configure_rate_limiter(old)


KNOWN = {"_wf_echo", "list_tables", "delete_calendar_event"}


def _step(tool, args=None):
    return {"tool": tool, "args": dict(args or {})}


# --- validation -------------------------------------------------


def test_valid_minimal():
    name, desc, steps = wf_svc.validate_workflow(
        "demo", [_step("_wf_echo", {"text": "hi {{input}}"})], "d", KNOWN)
    assert name == "demo" and len(steps) == 1


def test_empty_name_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow("  ", [_step("_wf_echo")], "", KNOWN)


def test_no_steps_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow("x", [], "", KNOWN)


def test_too_many_steps_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo") for _ in range(11)], "", KNOWN)


def test_unknown_tool_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow("x", [_step("nope")], "", KNOWN)


def test_removed_gmail_tool_rejected_as_unknown():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow("x", [_step("send_gmail", {"to": "a"})], "", KNOWN)


def test_forward_ref_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo", {"text": "{{steps.1.output}}"}),
                  _step("_wf_echo")], "", KNOWN)


def test_out_of_range_ref_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo"), _step("_wf_echo", {"text": "{{steps.7.output}}"})],
            "", KNOWN)


def test_unknown_template_shape_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo", {"text": "hi {{bogus}}"})], "", KNOWN)


@pytest.mark.parametrize("arg", ["code", "sql", "table", "upload_id", "server", "tool"])
def test_static_args_reject_step_templates(arg):
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo"), _step("_wf_echo", {arg: "{{steps.0.output}}"})],
            "", KNOWN | {"_wf_echo"})


def test_static_args_allow_input():
    _name, _desc, steps = wf_svc.validate_workflow(
        "x", [_step("_wf_echo", {"code": "print('{{input}}')"})], "", KNOWN)
    assert steps[0]["args"]["code"] == "print('{{input}}')"


def test_confirm_string_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo", {"confirm": "{{steps.0.output}}"})], "", KNOWN)


def test_confirm_bool_rejected():
    # Interactive approval flags have no meaning in saved pipelines.
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo", {"confirm": True})], "", KNOWN)


def test_approval_token_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo", {"approval_token": "abc"})], "", KNOWN)


def test_non_scalar_arg_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo", {"text": ["nested"]})], "", KNOWN)


def test_arg_too_long_rejected():
    with pytest.raises(ValueError):
        wf_svc.validate_workflow(
            "x", [_step("_wf_echo", {"text": "y" * 5000})], "", KNOWN)


# --- rendering --------------------------------------------------


def test_render_input_and_steps():
    rendered, err = wf_svc.render_args(
        {"text": "{{input}}|{{steps.0.output}}|{{ steps.1.output }}"},
        "hi", ["a", "b"])
    assert err is None
    assert rendered == {"text": "hi|a|b"}


def test_render_missing_output_errors():
    _rendered, err = wf_svc.render_args({"text": "{{steps.3.output}}"}, "hi", ["a"])
    assert err is not None


def test_render_overlong_errors():
    _rendered, err = wf_svc.render_args({"text": "{{input}}"}, "y" * 5000, [])
    assert err is not None


# --- storage ----------------------------------------------------


def _store():
    return UserStore("wf-user")


def test_storage_crud_roundtrip():
    store = _store()
    rec = store.create_workflow(
        "pipe", [_step("_wf_echo", {"text": "{{input}}"})], "desc", KNOWN)
    assert rec["id"] and rec["name"] == "pipe"
    assert store.get_workflow(rec["id"])["steps"][0]["tool"] == "_wf_echo"
    assert [w["id"] for w in store.list_workflows()] == [rec["id"]]
    updated = store.update_workflow(
        rec["id"], "pipe2", [_step("_wf_echo"), _step("_wf_echo")], "", KNOWN)
    assert updated["name"] == "pipe2" and len(updated["steps"]) == 2
    assert updated["created"] == rec["created"]
    assert store.delete_workflow(rec["id"]) is True
    assert store.get_workflow(rec["id"]) is None


def test_storage_rejects_invalid():
    store = _store()
    with pytest.raises(ValueError):
        store.create_workflow("", [_step("_wf_echo")], "", KNOWN)
    with pytest.raises(ValueError):
        store.update_workflow("0" * 16, "x", [_step("_wf_echo")], "", KNOWN)
    assert store.delete_workflow("0" * 16) is False
    assert store.get_workflow("not-an-id") is None


def test_storage_registry_cap():
    store = _store()
    for i in range(50):
        store.create_workflow(f"w{i}", [_step("_wf_echo")], "", KNOWN)
    with pytest.raises(ValueError):
        store.create_workflow("overflow", [_step("_wf_echo")], "", KNOWN)


# --- runner -----------------------------------------------------


def _rec(steps):
    return {"id": "a" * 16, "name": "r", "description": "",
            "steps": steps, "created": 0.0, "updated": 0.0}


def test_run_happy_path_templating():
    out = run_workflow(_rec([
        _step("_wf_echo", {"text": "a"}),
        _step("_wf_echo", {"text": "{{steps.0.output}}+b"}),
        _step("_wf_echo", {"text": "{{input}}!"}),
    ]), "hi", "wf-user", "wf-user")
    assert out["status"] == "ok", out
    outputs = [s["output"] for s in out["steps"]]
    # Tool-funnel envelope is reported verbatim (templates chain the
    # reported value, so step 2 visibly contains step 1's output).
    assert all(o.startswith("STATUS=OK") for o in outputs), out
    assert "echo:a" in outputs[0]
    assert "echo:hi!" in outputs[2]
    assert outputs[0] in outputs[1] and outputs[1].endswith("+b\n</untrusted_tool_output>")
    assert out["tools_used"] == ["_wf_echo"]
    assert out["error"] == ""


def test_run_stops_on_failure():
    out = run_workflow(_rec([
        _step("_wf_echo", {"text": "ok"}),
        _step("_wf_echo", {"text": "boom"}),
        _step("_wf_echo", {"text": "never"}),
    ]), "", "wf-user", "wf-user")
    assert out["status"] == "failed", out
    assert len(out["steps"]) == 2
    assert out["steps"][0]["ok"] is True
    assert out["steps"][1]["ok"] is False
    assert out["error"] != ""


def test_run_unknown_tool_preflight_runs_nothing():
    out = run_workflow(_rec([_step("nope")]), "", "wf-user", "wf-user")
    assert out["status"] == "failed"
    assert out["steps"] == []


def test_run_empty_workflow_failed():
    out = run_workflow(_rec([]), "", "wf-user", "wf-user")
    assert out["status"] == "failed"


def test_run_never_raises_on_garbage():
    assert run_workflow("garbage", "", "wf-user", "wf-user")["status"] == "failed"
    assert run_workflow(None, "", "wf-user", "wf-user")["status"] == "failed"


def test_run_budget_partial():
    import time as _time

    out = run_workflow(_rec([_step("_wf_echo", {"text": "a"})]), "",
                       "wf-user", "wf-user",
                       budget=RequestBudget(deadline=_time.time() - 1))
    assert out["status"] == "partial", out


def test_run_input_truncated_flag():
    out = run_workflow(_rec([_step("_wf_echo", {"text": "{{input}}"})]),
                       "y" * 5000, "wf-user", "wf-user")
    assert out["status"] == "ok", out
    assert out["input_truncated"] is True


# --- API --------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "api-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.setitem(TOOL_MAP, "_wf_echo", _wf_echo)
    from backend.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as handle:
        yield handle


def test_api_crud_and_run(client):
    created = client.post("/api/workflows", json={
        "name": "demo",
        "description": "d",
        "steps": [{"tool": "_wf_echo", "args": {"text": "hi {{input}}"}}],
    })
    assert created.status_code == 201, created.text
    wid = created.json()["id"]
    assert client.get("/api/workflows").status_code == 200
    assert client.get(f"/api/workflows/{wid}").status_code == 200
    updated = client.put(f"/api/workflows/{wid}", json={
        "name": "demo2", "description": "",
        "steps": [{"tool": "_wf_echo", "args": {"text": "v2"}}],
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "demo2"
    run = client.post(f"/api/workflows/{wid}/run", json={"input": ""})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "ok", body
    assert body["steps"][0]["output"].startswith("STATUS=OK")
    assert "echo:v2" in body["steps"][0]["output"]
    assert client.delete(f"/api/workflows/{wid}").status_code == 200
    assert client.get(f"/api/workflows/{wid}").status_code == 404


def test_api_create_invalid(client):
    bad = client.post("/api/workflows", json={
        "name": "bad", "description": "",
        "steps": [{"tool": "nope", "args": {}}],
    })
    assert bad.status_code == 400


def test_api_run_404(client):
    assert client.post("/api/workflows/" + "0" * 16 + "/run",
                       json={"input": ""}).status_code == 404


def test_api_create_blocked_tool(client):
    bad = client.post("/api/workflows", json={
        "name": "bad", "description": "",
        "steps": [{"tool": "send_gmail", "args": {"to": "a@b.c"}}],
    })
    assert bad.status_code == 400
