"""Sandboxed Python execution core: pure computation, no capabilities.

Threat model: the private-mode caller is the trusted owner, but the CODE
often originates from the model, which may be steered by untrusted
prompt-injected content (tool output, documents, memory). The sandbox
therefore removes every exfiltration and persistence capability — no
imports, no file/network/process access, no dunder introspection — while
keeping pure computation (arithmetic, strings, collections, functions,
print). A prompt-injected snippet can at worst burn bounded CPU.

This is a prompt-injection-grade sandbox, NOT a kernel boundary: a
hostile owner can always DoS their own process (e.g. giant in-memory
structures, which no AST check can distinguish from legitimate big-int
math). Hosts needing hard isolation must containerize the API process.
Callers must additionally gate on private mode (tools.python_tool).

Defenses, in order:
1. Length cap (services.limits.MAX_PYTHON_CODE_CHARS).
2. AST validation: no imports, no `while` (unbounded spins orphan pool
   threads past the timeout), no async, no private/dunder names or
   attributes, no dangerous builtins (eval/exec/open/...).
3. Iteration budget: every `for` loop and comprehension iterable is
   wrapped in a guard, and `range` is replaced with a bounded version —
   both enforced against MAX_PYTHON_ITERATIONS.
4. Restricted builtins: ~30 harmless functions + common exceptions (so
   try/except works). `__builtins__` is pinned explicitly because exec
   would otherwise inject the real ones.
5. Wall-clock timeout + rate limit + output cap at the tool layer.
"""

import ast
import contextlib
import io
import json as _json
import logging as _logging
import os as _os
import subprocess as _subprocess
import sys as _sys
import threading as _threading
from typing import Any, Dict, Optional

_logger = _logging.getLogger(__name__)

from services.limits import (
    MAX_PYTHON_CHILD_RSS_BYTES,
    MAX_PYTHON_CODE_CHARS,
    MAX_PYTHON_EXEC_SECONDS,
    MAX_PYTHON_ITERATIONS,
    MAX_PYTHON_OUTPUT_CHARS,
    MAX_PYTHON_PROCS,
)

# Name injected into builtins for the AST-added iteration guard. The
# validator runs BEFORE the transform, so user code can never reference
# it (underscore names are rejected); the guard call is added after.
_GUARD_NAME = "_pluto_guard_iter"

_BLOCKED_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.While,
    ast.AsyncFunctionDef,
    ast.AsyncFor,
    ast.AsyncWith,
    ast.Await,
)

# Dangerous builtins: rejected at validation for a clean INVALID marker
# (they are also absent from the runtime builtins as defense in depth).
_BLOCKED_CALLS = frozenset({
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
})


class _IterationBudgetExceeded(Exception):
    """Raised when sandboxed code exceeds its iteration budget."""


class _OutputBudgetExceeded(Exception):
    """Raised when sandboxed code exceeds its output budget."""


def validate_code(code: str) -> Optional[str]:
    """Check code against the sandbox policy.

    Returns None when allowed, else a short human-readable reason (no
    code echo, to keep markers compact).
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return "invalid Python syntax (%s at line %s)" % (e.msg, e.lineno)
    except (ValueError, RecursionError, MemoryError) as e:
        return "unparseable code (%s)" % (type(e).__name__,)
    for node in ast.walk(tree):
        if isinstance(node, _BLOCKED_NODES):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                return "imports are not allowed in the sandbox"
            if isinstance(node, ast.While):
                return "'while' loops are not allowed (use 'for' with range())"
            return "async code is not allowed in the sandbox"
        # Reject any name starting with '_' in any context (Name, Attribute,
        # FunctionDef, ClassDef, AsyncFunctionDef, arg, ExceptHandler)
        # to prevent shadowing the injected iteration guard.
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            return "private name %r is not allowed" % (node.id,)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return "private attribute %r is not allowed" % (node.attr,)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_"):
                return "private name %r is not allowed" % (node.name,)
        if isinstance(node, ast.arg):
            if node.arg.startswith("_"):
                return "private name %r is not allowed" % (node.arg,)
        if isinstance(node, ast.ExceptHandler) and node.name and node.name.startswith("_"):
            return "private name %r is not allowed" % (node.name,)
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _BLOCKED_CALLS:
                return "%s() is not allowed in the sandbox" % (func.id,)
    return None


def _guard_call(iter_node: ast.AST) -> ast.Call:
    """Wrap a loop/comprehension iterable: `ITER` -> `_guard(ITER)`."""
    call = ast.Call(
        func=ast.Name(id=_GUARD_NAME, ctx=ast.Load()),
        args=[iter_node],
        keywords=[],
    )
    return ast.copy_location(call, iter_node)


class _IterationGuard(ast.NodeTransformer):
    """Wrap every `for` target and comprehension iterable in the guard."""

    def visit_For(self, node: ast.For) -> ast.AST:
        self.generic_visit(node)
        node.iter = _guard_call(node.iter)
        return node

    def visit_comprehension(self, node: ast.comprehension) -> ast.AST:
        self.generic_visit(node)
        node.iter = _guard_call(node.iter)
        return node


_SAFE_EXCEPTIONS = (
    Exception,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    ZeroDivisionError,
    AttributeError,
    RuntimeError,
    StopIteration,
)


def _fresh_namespace() -> Dict[str, Any]:
    """Build the sealed exec namespace (builtins + iteration guard)."""
    state = {"count": 0}

    def _guard(it: Any) -> Any:
        for x in it:
            state["count"] += 1
            if state["count"] > MAX_PYTHON_ITERATIONS:
                raise _IterationBudgetExceeded(
                    "iteration budget exceeded (%d); break early or shrink the workload"
                    % (MAX_PYTHON_ITERATIONS,)
                )
            yield x

    def _bounded_range(*args: Any) -> Any:
        try:
            r = range(*args)
        except TypeError:
            raise
        # len(range) is O(1): reject giant ranges before iterating.
        if len(r) > MAX_PYTHON_ITERATIONS:
            raise _IterationBudgetExceeded(
                "range() of %d exceeds the iteration budget (%d)"
                % (len(r), MAX_PYTHON_ITERATIONS)
            )
        return r

    safe: Dict[str, Any] = {
        "print": print,
        "len": len,
        "abs": abs,
        "round": round,
        "pow": pow,
        "divmod": divmod,
        "sum": sum,
        "min": min,
        "max": max,
        "sorted": sorted,
        "reversed": reversed,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "any": any,
        "all": all,
        "iter": iter,
        "next": next,
        "isinstance": isinstance,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "set": set,
        "tuple": tuple,
        "frozenset": frozenset,
        "chr": chr,
        "ord": ord,
        "hex": hex,
        "oct": oct,
        "bin": bin,
        "format": format,
        "range": _bounded_range,
    }
    for exc in _SAFE_EXCEPTIONS:
        safe[exc.__name__] = exc
    return {"__builtins__": safe, _GUARD_NAME: _guard}


class _CappedBuffer(io.StringIO):
    """Stdout cap for sandboxed code (shared by parent/child paths)."""

    def write(self, s: str) -> int:
        # Incremental cap: fail fast instead of buffering 100MB then truncating.
        # Keep the head up to the cap so callers can return partial output.
        text = str(s)
        room = (MAX_PYTHON_OUTPUT_CHARS + 1024) - self.tell()
        if room <= 0:
            raise _OutputBudgetExceeded(
                f"output exceeded {MAX_PYTHON_OUTPUT_CHARS} chars"
            )
        if len(text) > room:
            super().write(text[:room])
            raise _OutputBudgetExceeded(
                f"output exceeded {MAX_PYTHON_OUTPUT_CHARS} chars"
            )
        return super().write(text)


def _run_guarded_source(code: str) -> Dict[str, Any]:
    """Validate, transform, compile and exec source in-process.

    Used by the sandbox child process. Never raises (returns error dicts).
    The parent re-validates before spawning, so this is defense in depth.
    """
    reason = validate_code(code)
    if reason is not None:
        return {"error": reason, "invalid": True}
    try:
        tree = ast.parse(code, mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        return {"error": "invalid Python code (%s)" % (type(e).__name__,), "invalid": True}
    tree = _IterationGuard().visit(tree)
    ast.fix_missing_locations(tree)
    try:
        compiled = compile(tree, "<sandbox>", "exec")
    except (SyntaxError, ValueError) as e:
        return {"error": "could not compile code (%s)" % (e,), "invalid": True}
    buf = _CappedBuffer()
    try:
        namespace = _fresh_namespace()
        with contextlib.redirect_stdout(buf):
            exec(compiled, namespace, namespace)  # noqa: S102 -- sandboxed
        out = buf.getvalue()
    except _OutputBudgetExceeded:
        try:
            partial = buf.getvalue()[:MAX_PYTHON_OUTPUT_CHARS]
        except Exception:
            partial = ""
        return {"output": partial, "truncated": True}
    except _IterationBudgetExceeded as e:
        return {"error": str(e), "invalid": False}
    except RecursionError:
        return {"error": "recursion limit exceeded", "invalid": False}
    except BaseException as exc:
        detail = ("%s: %s" % (type(exc).__name__, exc)).strip()
        return {"error": detail[:300] or type(exc).__name__, "invalid": False}
    out = str(out)
    if len(out) > MAX_PYTHON_OUTPUT_CHARS:
        return {"output": out[:MAX_PYTHON_OUTPUT_CHARS], "truncated": True}
    return {"output": out, "truncated": False}


def _child_main() -> None:
    """Subprocess entry point: read {code} from stdin, write result JSON."""
    try:
        raw = _sys.stdin.read()
    except Exception:
        raw = ""
    try:
        req = _json.loads(raw or "{}")
    except Exception:
        _sys.stdout.write(_json.dumps({"error": "invalid sandbox request", "invalid": True}))
        _sys.stdout.flush()
        return
    code = req.get("code", "")
    if not isinstance(code, str):
        code = str(code or "")
    try:
        result = _run_guarded_source(code)
    except BaseException as exc:  # last-resort guard; never leak a traceback
        try:
            result = {"error": type(exc).__name__, "invalid": False}
        except Exception:
            result = {"error": "execution failed", "invalid": False}
    try:
        _sys.stdout.write(_json.dumps(result))
        _sys.stdout.flush()
    except Exception:
        _logger.debug("sandbox child result write failed", exc_info=True)


_CHILD_RUNNER = "from services.codeexec import _child_main; _child_main()"

# Concurrency cap (Finding 4): timed-out bursts must shed fast instead of
# accumulating killable-but-expensive processes.
_exec_sema = _threading.Semaphore(MAX_PYTHON_PROCS)


def _limit_child_resources() -> None:
    """Best-effort child RLIMITs (POSIX only; called pre-exec)."""
    try:
        import resource as _resource
    except ImportError:
        return
    try:
        rss = int(MAX_PYTHON_CHILD_RSS_BYTES or 0)
        if rss > 0:
            _resource.setrlimit(_resource.RLIMIT_AS, (rss, rss))
    except Exception:
        _logger.debug("sandbox child RLIMIT_AS failed", exc_info=True)
    try:
        cpu = int(MAX_PYTHON_EXEC_SECONDS) + 5
        if cpu > 0 and hasattr(_resource, "RLIMIT_CPU"):
            _resource.setrlimit(_resource.RLIMIT_CPU, (cpu, cpu + 5))
    except Exception:
        _logger.debug("sandbox child RLIMIT_CPU failed", exc_info=True)


def execute(code: str) -> Dict[str, Any]:
    """Run code in the sandbox, capturing stdout. Never raises.

    Returns {"output": str, "truncated": bool} on completion (even with
    empty output), or {"error": str, "invalid": bool} — invalid for
    policy/syntax rejections, else runtime failures. Execution runs in
    a killable subprocess with a wall-clock timeout so giant-int/CPU
    burns the AST check cannot see are terminated instead of wedging a
    pool thread (Finding 4). AST/iteration/output restrictions are
    preserved (re-validated in the child).
    """
    if not isinstance(code, str) or not code.strip():
        return {"error": "no code provided", "invalid": True}
    if len(code) > MAX_PYTHON_CODE_CHARS:
        return {
            "error": "code too large (%d chars, limit %d)"
            % (len(code), MAX_PYTHON_CODE_CHARS),
            "invalid": True,
        }
    reason = validate_code(code)
    if reason is not None:
        return {"error": reason, "invalid": True}
    return _exec_timed(code)


def _timeout_result() -> Dict[str, Any]:
    return {
        "error": "timed out after %gs (break early or shrink the workload)"
        % (MAX_PYTHON_EXEC_SECONDS,),
        "invalid": False,
    }


def _exec_timed(source: Any) -> Dict[str, Any]:
    """Run sandbox source in a killable subprocess. Never raises.

    Keeps the historical name/signature shape (execute() passes source;
    a compiled code object is rejected as invalid to avoid executing
    unvalidatable bytecode).
    """
    if not isinstance(source, str):
        return {"error": "invalid sandbox payload", "invalid": True}
    if not _exec_sema.acquire(blocking=False):
        return {"error": "executor saturated; please retry in a moment.", "invalid": False}
    try:
        return _exec_in_child(source)
    finally:
        try:
            _exec_sema.release()
        except Exception:
            _logger.debug("sandbox semaphore release failed", exc_info=True)


def _exec_in_child(source: str) -> Dict[str, Any]:
    """Spawn the sandbox child, enforce timeout+kill+cleanup. Never raises."""
    payload = _json.dumps({"code": source}).encode("utf-8")
    preexec = _limit_child_resources if _os.name == "posix" else None
    # The child must import services.codeexec: parent sys.path tweaks
    # (tests insert the repo root at runtime) are not inherited across
    # exec, so pin the repo root via PYTHONPATH explicitly.
    try:
        _repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        _child_env = dict(_os.environ)
        _existing_py = _child_env.get("PYTHONPATH", "")
        _child_env["PYTHONPATH"] = _repo_root + (_os.pathsep + _existing_py if _existing_py else "")
    except Exception:
        _child_env = None
    try:
        proc = _subprocess.Popen(  # noqa: S603 -- fixed argv (own interpreter + sealed runner), no shell
            [_sys.executable, "-c", _CHILD_RUNNER],
            stdin=_subprocess.PIPE,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.DEVNULL,
            preexec_fn=preexec,  # POSIX only; None on Windows
            close_fds=True,
            env=_child_env,
        )
    except Exception:
        _logger.debug("sandbox spawn failed", exc_info=True)
        return {"error": "could not start sandbox", "invalid": False}
    try:
        try:
            out, _ = proc.communicate(input=payload, timeout=MAX_PYTHON_EXEC_SECONDS)
        except _subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                _logger.debug("sandbox kill failed", exc_info=True)
            try:
                proc.wait(timeout=5)
            except Exception:
                _logger.debug("sandbox wait failed", exc_info=True)
            try:
                if proc.stdout:
                    proc.stdout.close()
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                _logger.debug("sandbox pipe close failed", exc_info=True)
            return _timeout_result()
        raw = (out or b"").decode("utf-8", errors="replace")
        if len(raw) > MAX_PYTHON_OUTPUT_CHARS + 4096:
            # Child protocol violation or runaway: do not trust it.
            return {"error": "sandbox returned too much data", "invalid": False}
        try:
            result = _json.loads(raw or "{}")
        except Exception:
            if proc.returncode not in (0, None):
                return _timeout_result()
            return {"error": "sandbox returned invalid data", "invalid": False}
        if not isinstance(result, dict):
            return {"error": "sandbox returned invalid data", "invalid": False}
        if "output" in result and "error" not in result:
            out_text = str(result.get("output", ""))
            if len(out_text) > MAX_PYTHON_OUTPUT_CHARS + 1:
                out_text = out_text[:MAX_PYTHON_OUTPUT_CHARS]
                return {"output": out_text, "truncated": True}
            return {"output": out_text, "truncated": bool(result.get("truncated", False))}
        err_text = str(result.get("error", "") or "execution failed")[:500]
        return {"error": err_text, "invalid": bool(result.get("invalid", False))}
    finally:
        try:
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    _logger.debug("sandbox cleanup kill failed", exc_info=True)
                try:
                    proc.wait(timeout=5)
                except Exception:
                    _logger.debug("sandbox cleanup wait failed", exc_info=True)
        except Exception:
            _logger.debug("sandbox cleanup failed", exc_info=True)
