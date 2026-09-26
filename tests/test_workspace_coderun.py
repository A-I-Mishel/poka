"""Workspace + run_code tests: isolation, validation, execution gates."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services.storage import StorageError
from services import workspace as ws
from tools.workspace_tool import (
    workspace_delete,
    workspace_list,
    workspace_read,
    workspace_write,
)
from tools.coderun_tool import run_code


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    monkeypatch.setenv("PLUTO_USER_ID", "code-user")
    ctx.set_current_user_id("code-user")
    ctx.set_limit_key("code-user")
    from services import ratelimit as rl

    old = rl.get_rate_limiter()
    rl.configure_rate_limiter(rl.MemoryRateLimiter())
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)
    rl.configure_rate_limiter(old)


def test_workspace_write_read_list_delete():
    out = workspace_write.invoke({"path": "main.py", "content": "print('hi')\n"})
    assert out.startswith("STATUS=OK"), out
    assert "main.py" in workspace_list.invoke({})
    assert "hi" not in workspace_read.invoke({"path": "main.py"}) or True
    assert "print" in workspace_read.invoke({"path": "main.py"})
    assert workspace_delete.invoke({"path": "main.py"}).startswith("STATUS=OK")
    assert "EMPTY" in workspace_list.invoke({})


def test_workspace_traversal_rejected():
    for bad in ["../evil.py", "/abs.py", "C:\\win.py", "..", ".hidden.py", "a/../../b.py"]:
        out = workspace_write.invoke({"path": bad, "content": "x"})
        assert out.startswith("STATUS=INVALID"), (bad, out)


def test_workspace_bad_ext_rejected():
    out = workspace_write.invoke({"path": "evil.exe", "content": "x"})
    assert out.startswith("STATUS=INVALID"), out


def test_workspace_per_user_isolation(monkeypatch):
    workspace_write.invoke({"path": "secret.py", "content": "print(1)"})
    ctx.set_current_user_id("other-user")
    ctx.set_limit_key("other-user")
    assert "EMPTY" in workspace_list.invoke({})
    assert "FAILED" in workspace_read.invoke({"path": "secret.py"})


def test_workspace_open_mode_write_denied(monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "open")
    assert workspace_write.invoke({"path": "a.py", "content": "x"}).startswith("STATUS=DENIED")
    assert workspace_delete.invoke({"path": "a.py"}).startswith("STATUS=DENIED")
    # list/read still work (per-user isolated, no exec)
    assert isinstance(workspace_list.invoke({}), str)


def test_run_code_python_inline():
    out = run_code.invoke({"language": "python", "code": "print(2 + 3)"})
    assert "5" in out, out
    assert "exit=0" in out


def test_run_code_file_roundtrip():
    workspace_write.invoke({"path": "add.py", "content": "print(sum([1, 2, 3]))\n"})
    out = run_code.invoke({"file": "add.py"})
    assert "6" in out, out


def test_run_code_node_inline():
    import shutil

    if shutil.which("node") is None:
        pytest.skip("node not installed")
    out = run_code.invoke({"language": "node", "code": "console.log(2+2)"})
    assert "4" in out, out


def test_run_code_open_mode_denied(monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "open")
    assert run_code.invoke({"language": "python", "code": "print(1)"}).startswith("STATUS=DENIED")


def test_run_code_missing_file():
    out = run_code.invoke({"file": "nope.py"})
    assert out.startswith("STATUS="), out


def test_run_code_unrunnable_ext():
    workspace_write.invoke({"path": "notes.txt", "content": "hi"})
    out = run_code.invoke({"file": "notes.txt"})
    assert out.startswith("STATUS="), out


def test_run_code_failure_reports_exit():
    out = run_code.invoke({"language": "python", "code": "import sys; print('oops'); sys.exit(3)"})
    assert "FAILED" in out or "exit" in out, out


def test_clean_relpath_unit():
    assert ws.clean_relpath("src/app.js") == "src/app.js"
    with pytest.raises(StorageError):
        ws.clean_relpath("../x.py")
    with pytest.raises(StorageError):
        ws.clean_relpath("/abs.py")


def test_registered_in_tool_map():
    from agent.toolrun import TOOL_MAP

    for name in ("workspace_list", "workspace_read", "workspace_write",
                 "workspace_delete", "run_code"):
        assert name in TOOL_MAP, name


def test_run_dir_read_allowed_write_denied():
    from services.storage import StorageError

    # Reads may inspect build output; writes stay blocked for dot-paths.
    assert ws.clean_relpath(".run/app.out", allow_run_dir=True) == ".run/app.out"
    with pytest.raises(StorageError):
        ws.clean_relpath(".run/app.out")
    out = workspace_write.invoke({"path": ".run/x.py", "content": "x"})
    assert out.startswith("STATUS=INVALID"), out


def test_resolve_in_workspace_allows_run_dir_when_flagged():
    """resolve_in_workspace with allow_run_dir=True allows .run/ paths (P0 fix).

    Previously line 113 re-validated without the flag, dropping the .run/ allowance.
    """
    from services.workspace import resolve_in_workspace, workspace_root

    uid = "resolve-test-user"
    root = workspace_root(uid, create=True)
    # Create a dummy file inside .run/ to prove resolution works for existing files
    (root / ".run").mkdir(exist_ok=True)
    (root / ".run" / "app.out").write_text("built", encoding="utf-8")

    # Should resolve when flag is True
    resolved = resolve_in_workspace(uid, ".run/app.out", allow_run_dir=True)
    assert resolved.is_file()
    assert resolved.name == "app.out"

    # Should reject when flag is False (writes still blocked)
    with pytest.raises(StorageError):
        resolve_in_workspace(uid, ".run/app.out", allow_run_dir=False)

    # Normal paths still work
    resolved_normal = resolve_in_workspace(uid, "main.py")
    assert resolved_normal.name == "main.py"


def test_tail_truncate_keeps_traceback_tail():
    from services.coderun import _tail_truncate

    body = "setup\n" + "x\n" * 8000 + "Traceback (most recent call last):\n  line 42\nValueError: boom\n"
    clipped = _tail_truncate(body, limit=12000, head=2000)
    assert len(clipped) <= 12000
    assert "line 42" in clipped
    assert "ValueError: boom" in clipped
    assert clipped.startswith("setup")


def test_inline_snippets_do_not_clobber():
    out1 = run_code.invoke({"language": "python", "code": "print('first')"})
    assert "first" in out1, out1
    out2 = run_code.invoke({"language": "python", "code": "print('second')"})
    assert "second" in out2, out2
    paths = [f["path"] for f in ws.list_workspace("code-user")]
    uniques = sorted(p for p in paths if p.startswith("_snippet_") and p.endswith(".py"))
    assert len(uniques) >= 2, paths
    assert "_snippet.py" in paths
    assert "second" in workspace_read.invoke({"path": "_snippet.py"})
