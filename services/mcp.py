"""Generic MCP client: use tools from any configured MCP server.

Servers come from PLUTO_MCP_SERVERS (JSON list). Each entry names the
server plus ONE transport:

    {"name": "github", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-github"],
     "env": {"GITHUB_TOKEN": "PLUTO_MCP_GITHUB_TOKEN"}}
    {"name": "docs", "url": "https://mcp.example.com/mcp",
     "headers": {"Authorization": "Bearer static-token"}}

`"env"` values name environment variables to read (never literal
secrets in config). Stdio servers suit local dev (need node/npx);
remote HTTP/SSE servers suit hosted deploys (no subprocess).

Safety: PLUTO_MCP_ALLOW_TOOLS gates everything (comma-separated
"server.tool" or "server.*" globs; default deny). Third-party tool
output is untrusted DATA. Each call opens a fresh session (slower
for stdio, but leak-free); the tool layer's own timeout still bounds
every call. The `mcp` package is imported lazily so everything
degrades (not crashes) without it.

Test seam: configure_connector() installs a fake
(cfg, op, payload) callable; real sessions are never needed in tests.
"""

import asyncio
import fnmatch
import json
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, List, Optional

from services.limits import MCP_TIMEOUT_SECONDS
from services.obs import event as obs_event
from services.secrets import get_secret

MAX_TOOL_ARG_CHARS: int = 8000
MAX_OUTPUT_CHARS: int = 12000

_connector: Optional[Callable[[Dict[str, Any], str, Any], Any]] = None


def configure_connector(fn: Optional[Callable[[Dict[str, Any], str, Any], Any]]) -> None:
    """Install a fake connector (tests), or None to restore the real one."""
    global _connector
    _connector = fn


def _resolve_headers(mapping: Any) -> Dict[str, str]:
    """Resolve remote-server headers, preferring env references.

    Values shaped "env:NAME" resolve via the secret seam (never commit
    literals); plain values pass through for backward compat but should
    be migrated (a literal Bearer in PLUTO_MCP_SERVERS lives in env
    config — rotate it if leaked).
    """
    resolved: Dict[str, str] = {}
    if not isinstance(mapping, dict):
        return resolved
    for key, value in mapping.items():
        text = str(value or "")
        if text.startswith("env:"):
            secret = get_secret(text[4:].strip(), "")
            if secret:
                resolved[str(key)] = secret
        elif text:
            resolved[str(key)] = text
    return resolved


def load_servers() -> List[Dict[str, Any]]:
    """Parse configured MCP servers; [] on missing/garbage (never raises)."""
    raw = (get_secret("PLUTO_MCP_SERVERS", "") or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        if entry.get("url"):
            out.append({"name": name, "url": str(entry["url"]),
                        "headers": _resolve_headers(entry.get("headers"))})
        elif entry.get("command"):
            out.append({"name": name, "command": str(entry["command"]),
                        "args": entry.get("args") or [],
                        "env": entry.get("env") or {}})
    return out


def get_server(name: str) -> Optional[Dict[str, Any]]:
    """Configured server by name, or None."""
    for entry in load_servers():
        if entry["name"] == name:
            return entry
    return None


def server_names() -> List[str]:
    """Configured server names."""
    return [entry["name"] for entry in load_servers()]


def allowed(server: str, tool: str) -> bool:
    """Allowlist check: PLUTO_MCP_ALLOW_TOOLS globs, default deny."""
    raw = (get_secret("PLUTO_MCP_ALLOW_TOOLS", "") or "").strip()
    if not raw:
        return False
    target = "%s.%s" % (server, tool)
    for pattern in (p.strip() for p in raw.split(",")):
        if pattern and fnmatch.fnmatchcase(target, pattern):
            return True
    return False


def _resolve_env(mapping: Any) -> Dict[str, str]:
    """Resolve {VAR: SECRET_NAME} via the secret seam (never literals)."""
    resolved: Dict[str, str] = {}
    if not isinstance(mapping, dict):
        return resolved
    for var, secret_name in mapping.items():
        value = get_secret(str(secret_name), "")
        if value:
            resolved[str(var)] = value
    return resolved


def _base_env() -> Dict[str, str]:
    """Small safe base env for stdio children (delegates to services.env)."""
    from services.env import base_env as _shared_base_env

    return _shared_base_env()


def _stdio_env(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Build the exact env for a stdio MCP server: safe base + resolved secrets."""
    return {**_base_env(), **_resolve_env(cfg.get("env"))}


@asynccontextmanager
async def _open_session(cfg: Dict[str, Any]):
    """Yield an initialized MCP ClientSession for one server config."""
    try:
        from mcp import ClientSession
    except ImportError:
        raise RuntimeError("The 'mcp' package is not installed.")
    if cfg.get("url"):
        try:
            from mcp.client.streamablehttp import streamablehttp_client as http_client
        except ImportError:
            from mcp.client.sse import sse_client as http_client
        headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
        async with http_client(str(cfg["url"]), headers=dict(headers)) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), MCP_TIMEOUT_SECONDS)
                yield session
    else:
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=str(cfg["command"]),
            args=[str(a) for a in (cfg.get("args") or [])],
            # NOTE: the installed `mcp` SDK merges `env` over its own
            # get_default_environment(), so passing only the minimal base +
            # resolved secrets is sufficient — and prevents leaking the full
            # process env (API keys, tokens) to third-party server binaries.
            env=_stdio_env(cfg),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), MCP_TIMEOUT_SECONDS)
                yield session


async def _list_async(cfg: Dict[str, Any]) -> List[Dict[str, str]]:
    async with _open_session(cfg) as session:
        result = await asyncio.wait_for(session.list_tools(), MCP_TIMEOUT_SECONDS)
        return [{"name": str(t.name), "description": str(getattr(t, "description", "") or "")}
                for t in (result.tools if result is not None else [])]


async def _call_async(cfg: Dict[str, Any], tool: str, args: Dict[str, Any]) -> str:
    async with _open_session(cfg) as session:
        result = await asyncio.wait_for(
            session.call_tool(tool, args), MCP_TIMEOUT_SECONDS)
        if getattr(result, "isError", False):
            raise RuntimeError(_format_content(getattr(result, "content", [])) or "MCP tool error.")
        return _format_content(getattr(result, "content", []))


def _format_block(block: Any) -> str:
    if isinstance(block, dict):
        kind = str(block.get("type", "text"))
        if kind == "text":
            return str(block.get("text", ""))
        if kind in ("image", "audio"):
            return "[%s content omitted: %s]" % (kind, block.get("mimeType", ""))
        if kind == "resource":
            inner = block.get("resource", {})
            if isinstance(inner, dict):
                return str(inner.get("text", inner.get("uri", "")))
            return str(inner)
        return str(block.get("text", ""))
    kind = str(getattr(block, "type", "text") or "text")
    if kind == "text":
        return str(getattr(block, "text", ""))
    if kind in ("image", "audio"):
        return "[%s content omitted: %s]" % (kind, getattr(block, "mimeType", ""))
    if kind == "resource":
        inner = getattr(block, "resource", None)
        if inner is None:
            return ""
        return str(getattr(inner, "text", getattr(inner, "uri", "")))
    return str(getattr(block, "text", ""))


def _format_content(content: Any) -> str:
    if not content:
        return ""
    items = content if isinstance(content, list) else [content]
    text = "\n".join(t for t in (_format_block(b) for b in items) if t)
    # Bound third-party output before it reaches the tool funnel (which
    # applies its own MAX_TOOL_RESULT_TOKENS cap downstream).
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + "\n[Note: MCP output truncated.]"
    return text


def list_server_tools(server: str) -> List[Dict[str, str]]:
    """List one server's tools (raises RuntimeError on failure)."""
    cfg = get_server(server)
    if cfg is None:
        raise RuntimeError("Unknown MCP server: %s." % server)
    if _connector is not None:
        return _connector(cfg, "list", None)
    try:
        return asyncio.run(_list_async(cfg))
    except RuntimeError:
        raise
    except Exception as e:
        obs_event("mcp.error", action="list", server=server)
        raise RuntimeError(f"MCP list failed for {server}: {e}")


def call_server_tool(server: str, tool: str, args: Dict[str, Any]) -> str:
    """Call one server tool; returns text (raises RuntimeError on failure)."""
    cfg = get_server(server)
    if cfg is None:
        raise RuntimeError("Unknown MCP server: %s." % server)
    if _connector is not None:
        return _connector(cfg, "call", {"tool": tool, "args": args})
    try:
        return asyncio.run(_call_async(cfg, tool, args or {}))
    except RuntimeError:
        raise
    except Exception as e:
        obs_event("mcp.error", action="call", server=server)
        raise RuntimeError(f"MCP call failed for {server}.{tool}: {e}")
