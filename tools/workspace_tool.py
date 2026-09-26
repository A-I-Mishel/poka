"""Workspace tools: per-user source files for real coding work.

- workspace_list / workspace_read: per-user isolated, allowed in any
  auth mode (still needs a user context).
- workspace_write / workspace_delete: private-mode only (trusted owner),
  like code execution — open-mode visitors are denied outright.

All paths are workspace-relative (e.g. "main.py", "src/app.js") — never
absolute paths or upload IDs. Results carry STATUS= markers.
"""

from langchain_core.tools import tool

from services.identity import auth_mode
from services.obs import event as obs_event
from services.storage import StorageError
from services.workspace import (
    delete_workspace_file,
    list_workspace,
    read_workspace_file,
    write_workspace_file,
)
from tools.gating import claim_tool_slot


def _need_user(tool_name: str):
    return claim_tool_slot(tool_name, "code", "code")


def _need_private(tool_name: str, action: str = "code"):
    if auth_mode() != "private":
        obs_event("ratelimit.deny", action=action, tool=tool_name,
                  reason="open_mode")
        return None, (
            f"STATUS=DENIED tool={tool_name}: workspace writes are disabled "
            "in open mode. Set PLUTO_AUTH_MODE=private (trusted/owner use only)."
        )
    return claim_tool_slot(tool_name, "code", "code")


def _clean_path(path: str) -> str:
    """Tool-side defense-in-depth: reject absolute/.. /empty before service."""
    text = str(path or "").strip()
    if not text:
        raise ValueError("empty path")
    if text.startswith(("/", "\\", "~")) or ".." in text.split("/"):
        raise ValueError("path must be workspace-relative without '..'")
    if len(text) > 200:
        raise ValueError("Workspace path too long (limit 200).")
    return text


@tool
def workspace_list() -> str:
    """List files in your private code workspace.

    Returns one relative path per line with sizes, or STATUS=EMPTY when
    the workspace has no files yet. Use workspace_write to create files.
    """
    user_id, err = _need_user("workspace_list")
    if user_id is None:
        return err
    try:
        files = list_workspace(user_id)
    except Exception as e:
        return f"STATUS=FAILED tool=workspace_list: {str(e)[:200]}"
    if not files:
        return "STATUS=EMPTY tool=workspace_list: workspace is empty (use workspace_write to create e.g. main.py)."
    shown = files[:100]
    lines = [f"{f['path']} ({int(f['size'])} bytes)" for f in shown]
    if len(files) > len(shown):
        lines.append(f"[Note: +{len(files) - len(shown)} more.]")
    return "\n".join(lines)


@tool
def workspace_read(path: str) -> str:
    """Read a workspace source file as text (capped).

    Args:
        path: Workspace-relative path, e.g. "main.py" or "src/app.js".

    Returns:
        File text, or a STATUS= marker when missing/unreadable.
    """
    user_id, err = _need_user("workspace_read")
    if user_id is None:
        return err
    try:
        _clean_path(path)
    except ValueError as e:
        return f"STATUS=INVALID tool=workspace_read: {e}"
    try:
        text = read_workspace_file(user_id, str(path or ""))
    except FileNotFoundError as e:
        return f"STATUS=FAILED tool=workspace_read: {str(e)[:200]}"
    except StorageError as e:
        return f"STATUS=INVALID tool=workspace_read: {e}"
    except Exception as e:
        return f"STATUS=FAILED tool=workspace_read: {str(e)[:200]}"
    if not text.strip():
        return "STATUS=EMPTY tool=workspace_read: file is empty."
    return text


@tool
def workspace_write(path: str, content: str) -> str:
    """Create or overwrite a workspace source file. Private mode only.

    Use for real coding: write main.py/app.js/etc, then run with
    run_code. Overwrites atomically. Quotas apply (100 files / 50 MiB).

    Args:
        path: Workspace-relative path, e.g. "main.py".
        content: Full file text (max ~100k chars).

    Returns:
        Confirmation with path + size, or a STATUS= marker.
    """
    user_id, err = _need_private("workspace_write")
    if user_id is None:
        return err
    try:
        _clean_path(path)
    except ValueError as e:
        return f"STATUS=INVALID tool=workspace_write: {e}"
    try:
        saved = write_workspace_file(user_id, str(path or ""), str(content or ""))
    except StorageError as e:
        return f"STATUS=INVALID tool=workspace_write: {e}"
    except Exception as e:
        return f"STATUS=FAILED tool=workspace_write: {str(e)[:200]}"
    ext = str(saved.get("path", "") or "").rsplit(".", 1)[-1].lower() if "." in str(saved.get("path", "")) else ""
    if ext in ("jsx", "tsx", "h", "hpp", "pyi"):
        return (f"STATUS=OK tool=workspace_write: saved {saved['path']} ({int(saved['size'])} bytes). "
                f"Note: .{ext} files cannot be executed directly "
                "(runnable: py, js/mjs/cjs, ts/mts, java, go, c, cpp, rs, php, rb).")
    return f"STATUS=OK tool=workspace_write: saved {saved['path']} ({int(saved['size'])} bytes). Run it with run_code."


@tool
def workspace_delete(path: str) -> str:
    """Delete one workspace file. Private mode only.

    Args:
        path: Workspace-relative path to delete.

    Returns:
        Confirmation, or STATUS=FAILED when missing.
    """
    user_id, err = _need_private("workspace_delete")
    if user_id is None:
        return err
    try:
        _clean_path(path)
    except ValueError as e:
        return f"STATUS=INVALID tool=workspace_delete: {e}"
    try:
        ok = delete_workspace_file(user_id, str(path or ""))
    except StorageError as e:
        return f"STATUS=INVALID tool=workspace_delete: {e}"
    except Exception as e:
        return f"STATUS=FAILED tool=workspace_delete: {str(e)[:200]}"
    if not ok:
        return "STATUS=INVALID tool=workspace_delete: file not found."
    return f"STATUS=OK tool=workspace_delete: deleted {path}."
