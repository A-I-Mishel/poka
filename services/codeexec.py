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
from typing import Any, Dict, Optional

from services.limits import (
    MAX_PYTHON_CODE_CHARS,
    MAX_PYTHON_ITERATIONS,
    MAX_PYTHON_OUTPUT_CHARS,
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
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            return "private name %r is not allowed" % (node.id,)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return "private attribute %r is not allowed" % (node.attr,)
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


def execute(code: str) -> Dict[str, Any]:
    """Run code in the sandbox, capturing stdout. Never raises.

    Returns {"output": str, "truncated": bool} on completion (even with
    empty output), or {"error": str, "invalid": bool} — invalid for
    policy/syntax rejections, else runtime failures. Execution runs on
    a daemon worker with a wall-clock timeout so giant-int/CPU burns
    the AST check cannot see fail instead of wedging a pool thread.
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
    return _exec_timed(compiled)


def _exec_timed(compiled: Any) -> Dict[str, Any]:
    """Run compiled sandbox code with a wall-clock bound. Never raises."""
    import threading as _threading

    from services.limits import MAX_PYTHON_EXEC_SECONDS

    buf = io.StringIO()
    outcome: Dict[str, Any] = {}
    errors: list = []

    def _run() -> None:
        try:
            namespace = _fresh_namespace()
            with contextlib.redirect_stdout(buf):
                exec(compiled, namespace, namespace)  # noqa: S102 -- sandboxed
            outcome["output"] = buf.getvalue()
        except BaseException as exc:  # captured, classified below
            errors.append(exc)

    worker = _threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(MAX_PYTHON_EXEC_SECONDS)
    if worker.is_alive():
        return {
            "error": "timed out after %gs (break early or shrink the workload)"
            % (MAX_PYTHON_EXEC_SECONDS,),
            "invalid": False,
        }
    if errors:
        exc = errors[0]
        if isinstance(exc, _IterationBudgetExceeded):
            return {"error": str(exc), "invalid": False}
        if isinstance(exc, RecursionError):
            return {"error": "recursion limit exceeded", "invalid": False}
        detail = ("%s: %s" % (type(exc).__name__, exc)).strip()
        return {"error": detail[:300] or type(exc).__name__, "invalid": False}
    out = str(outcome.get("output", ""))
    if len(out) > MAX_PYTHON_OUTPUT_CHARS:
        return {"output": out[:MAX_PYTHON_OUTPUT_CHARS], "truncated": True}
    return {"output": out, "truncated": False}
