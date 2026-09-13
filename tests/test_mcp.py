"""MCP tests: config, allowlist, gateway (stubbed) + live stdio round-trip.

Unit tests use a fake connector (no processes, no network). The live
test spawns a real FastMCP server over stdio and drives it through
the production client code (skipped without the mcp package).
"""

import importlib.util
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services import mcp as mcp_svc
from tools.mcp_tool import call_mcp_tool, list_mcp_tools

MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None

SERVERS_JSON = json.dumps([
    {"name": "gh", "command": "npx", "args": ["-y", "server-github"],
     "env": {"GITHUB_TOKEN": "PLUTO_MCP_GITHUB_TOKEN"}},
    {"name": "docs", "url": "https://mcp.example.com/mcp",
     "headers": {"Authorization": "Bearer static"}},
    {"name": "", "command": "nope"},
    "garbage-entry",
])


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLUTO_MCP_SERVERS", raising=False)
    monkeypatch.delenv("PLUTO_MCP_ALLOW_TOOLS", raising=False)
    ctx.set_current_user_id("mcp-user")
    ctx.set_limit_key("mcp-user")
    mcp_svc.configure_connector(None)
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)
    mcp_svc.configure_connector(None)


def _with_servers(monkeypatch, payload=SERVERS_JSON):
    monkeypatch.setenv("PLUTO_MCP_SERVERS", payload)


def test_config_parse(monkeypatch):
    _with_servers(monkeypatch)
    assert mcp_svc.server_names() == ["gh", "docs"]
    gh = mcp_svc.get_server("gh")
    assert gh["command"] == "npx" and gh["args"] == ["-y", "server-github"]
    assert mcp_svc.get_server("nope") is None


def test_config_garbage(monkeypatch):
    monkeypatch.setenv("PLUTO_MCP_SERVERS", "{not json")
    assert mcp_svc.load_servers() == []
    monkeypatch.setenv("PLUTO_MCP_SERVERS", '{"a": 1}')
    assert mcp_svc.load_servers() == []


def test_allowlist_default_deny(monkeypatch):
    _with_servers(monkeypatch)
    assert mcp_svc.allowed("gh", "anything") is False


def test_allowlist_globs(monkeypatch):
    _with_servers(monkeypatch)
    monkeypatch.setenv("PLUTO_MCP_ALLOW_TOOLS", "gh.get_issue, docs.*")
    assert mcp_svc.allowed("gh", "get_issue") is True
    assert mcp_svc.allowed("gh", "delete_repo") is False
    assert mcp_svc.allowed("docs", "search") is True
    assert mcp_svc.allowed("other", "search") is False


def _fake_connector(calls):
    def _fake(cfg, op, payload):
        calls.append((cfg["name"], op, payload))
        if op == "list":
            return [{"name": "get_issue", "description": "Fetch one issue"}]
        if payload["tool"] == "boom":
            raise RuntimeError("server exploded")
        return "issue #42: fix the login bug"

    return _fake


def test_list_via_connector(monkeypatch):
    _with_servers(monkeypatch)
    calls = []
    mcp_svc.configure_connector(_fake_connector(calls))
    out = list_mcp_tools.invoke({"server": "gh"})
    assert "gh.get_issue - Fetch one issue" in out
    assert calls and calls[0][0] == "gh"


def test_call_via_connector(monkeypatch):
    _with_servers(monkeypatch)
    monkeypatch.setenv("PLUTO_MCP_ALLOW_TOOLS", "gh.*")
    mcp_svc.configure_connector(_fake_connector([]))
    out = call_mcp_tool.invoke(
        {"server": "gh", "tool": "get_issue", "arguments": '{"n": 42}'})
    assert "issue #42" in out


def test_call_denied_without_allowlist(monkeypatch):
    _with_servers(monkeypatch)
    calls = []
    mcp_svc.configure_connector(_fake_connector(calls))
    out = call_mcp_tool.invoke({"server": "gh", "tool": "get_issue", "arguments": "{}"})
    assert out.startswith("STATUS=DENIED")
    assert calls == []


def test_call_bad_json(monkeypatch):
    _with_servers(monkeypatch)
    monkeypatch.setenv("PLUTO_MCP_ALLOW_TOOLS", "gh.*")
    out = call_mcp_tool.invoke({"server": "gh", "tool": "get_issue", "arguments": "{nope"})
    assert out.startswith("STATUS=INVALID")
    out = call_mcp_tool.invoke({"server": "gh", "tool": "get_issue", "arguments": "[1,2]"})
    assert out.startswith("STATUS=INVALID")


def test_call_unknown_server(monkeypatch):
    _with_servers(monkeypatch)
    monkeypatch.setenv("PLUTO_MCP_ALLOW_TOOLS", "*")
    out = call_mcp_tool.invoke({"server": "ghost", "tool": "x", "arguments": "{}"})
    assert out.startswith("STATUS=FAILED")


def test_connector_error_maps_to_failed(monkeypatch):
    _with_servers(monkeypatch)
    monkeypatch.setenv("PLUTO_MCP_ALLOW_TOOLS", "gh.*")
    mcp_svc.configure_connector(_fake_connector([]))
    out = call_mcp_tool.invoke({"server": "gh", "tool": "boom", "arguments": "{}"})
    assert out.startswith("STATUS=FAILED")


def test_unconfigured_degrades():
    assert list_mcp_tools.invoke({}).startswith("STATUS=DEGRADED")


def test_no_user_denied(monkeypatch):
    _with_servers(monkeypatch)
    ctx.set_current_user_id(None)
    assert list_mcp_tools.invoke({}).startswith("STATUS=DENIED")


def test_format_blocks():
    assert mcp_svc._format_content([{"type": "text", "text": "hi"}]) == "hi"
    assert "omitted" in mcp_svc._format_content([{"type": "image", "mimeType": "png"}])
    assert mcp_svc._format_content([{"type": "resource",
                                     "resource": {"uri": "f:///x", "text": "deep"}}]) == "deep"
    assert mcp_svc._format_content([]) == ""


def test_resolve_env(monkeypatch):
    monkeypatch.setenv("PLUTO_MCP_GITHUB_TOKEN", "tok-123")
    assert mcp_svc._resolve_env({"GITHUB_TOKEN": "PLUTO_MCP_GITHUB_TOKEN"}) == {"GITHUB_TOKEN": "tok-123"}
    assert mcp_svc._resolve_env({"MISSING": "PLUTO_MCP_NOPE"}) == {}


PROBE_SERVER = '''
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("probe")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


mcp.run()
'''


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp package required")
def test_live_stdio_roundtrip(tmp_path, monkeypatch):
    script = tmp_path / "probe_server.py"
    script.write_text(PROBE_SERVER, encoding="utf-8")
    cfg = {"name": "probe", "command": sys.executable, "args": [str(script)]}
    monkeypatch.setattr(mcp_svc, "load_servers", lambda: [cfg])
    monkeypatch.setenv("PLUTO_MCP_ALLOW_TOOLS", "probe.*")
    tools = mcp_svc.list_server_tools("probe")
    assert any(t["name"] == "add" for t in tools)
    assert mcp_svc.call_server_tool("probe", "add", {"a": 2, "b": 3}).strip() == "5"
