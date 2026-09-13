"""run_python tests: private-mode gate, sandbox rejections, happy path.

Uses a fresh in-process rate limiter per test (no quota coupling
between tests) and stubbed user context (no network, no credentials).
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import context as ctx
from services import codeexec
from tools.python_tool import run_python


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    monkeypatch.setenv("PLUTO_USER_ID", "py-user")
    ctx.set_current_user_id("py-user")
    ctx.set_limit_key("py-user")
    from services import ratelimit as rl

    old = rl.get_rate_limiter()
    rl.configure_rate_limiter(rl.MemoryRateLimiter())
    yield
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)
    rl.configure_rate_limiter(old)


def test_open_mode_denied(monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "open")
    out = run_python.invoke({"code": "print(1)"})
    assert out.startswith("STATUS=DENIED")
    assert "private" in out


def test_no_user_denied():
    ctx.set_current_user_id(None)
    ctx.set_limit_key(None)
    out = run_python.invoke({"code": "print(1)"})
    assert out.startswith("STATUS=DENIED")


def test_arithmetic_and_print():
    out = run_python.invoke({"code": "print(2 + 3 * 4)"})
    assert out.strip() == "14"


def test_functions_loops_and_try():
    code = (
        "def sq(n):\n"
        "    return n * n\n"
        "total = sum(sq(i) for i in range(5))\n"
        "try:\n"
        "    1 / 0\n"
        "except ZeroDivisionError:\n"
        "    total += 100\n"
        "print(total)"
    )
    assert run_python.invoke({"code": code}).strip() == "130"


def test_no_output_empty():
    out = run_python.invoke({"code": "x = 1"})
    assert out.startswith("STATUS=EMPTY")


def test_empty_code_invalid():
    assert run_python.invoke({"code": "  "}).startswith("STATUS=INVALID")


def test_code_too_long():
    out = run_python.invoke({"code": "print(1)\n" * 2000})
    assert out.startswith("STATUS=INVALID")


def test_syntax_error():
    assert run_python.invoke({"code": "def broken(:\n"}).startswith("STATUS=INVALID")


def test_runtime_error_reports_type():
    out = run_python.invoke({"code": "print(1 / 0)"})
    assert out.startswith("STATUS=FAILED")
    assert "ZeroDivisionError" in out


@pytest.mark.parametrize("code", [
    "import os",
    "from math import sqrt\nprint(sqrt(4))",
    "print(open('x').read())",
    "print(eval('1+1'))",
    "exec('print(1)')",
    "print((1).__class__)",
    "print(globals())",
    "print(__import__('os'))",
    "while True:\n    pass",
    "async def f():\n    pass",
    "x = __name__",
])
def test_sandbox_rejections(code):
    out = run_python.invoke({"code": code})
    assert out.startswith("STATUS=INVALID"), out


def test_huge_range_trips_budget_fast():
    started = time.time()
    out = run_python.invoke({"code": "s = 0\nfor i in range(10**9):\n    s += i\nprint(s)"})
    assert out.startswith("STATUS=FAILED"), out
    assert "budget" in out
    assert time.time() - started < 30


def test_huge_comprehension_trips_budget():
    out = run_python.invoke({"code": "print(sum([i for i in range(10**9)]))"})
    assert out.startswith("STATUS=FAILED"), out


def test_output_truncated():
    out = run_python.invoke({"code": "print('y' * 9000)"})
    assert "truncated" in out
    assert len(out) < 9000


def test_recursion_bounded():
    out = run_python.invoke({"code": "def f():\n    return f()\nf()"})
    assert out.startswith("STATUS=FAILED"), out


def test_registered_in_tool_map():
    from agent.toolrun import TOOL_MAP

    assert TOOL_MAP["run_python"] is run_python


def test_validate_unit():
    assert codeexec.validate_code("print('hi')") is None
    assert "import" in (codeexec.validate_code("import sys") or "")
    assert "while" in (codeexec.validate_code("while 1:\n pass") or "")
