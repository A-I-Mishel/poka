"""run_python: sandboxed Python for pure computation.

Private-mode only (PLUTO_AUTH_MODE=private): code execution is the
biggest security surface in the toolbox, so open mode (untrusted
visitors) is denied outright — the model cannot talk its way around
this gate. In private mode the AST sandbox (services.codeexec) still
removes every I/O and introspection capability: no imports, no files,
no network, no `while`, no dunders.
"""

from langchain_core.tools import tool

from services import codeexec
from services.identity import auth_mode
from services.limits import MAX_PYTHON_OUTPUT_CHARS
from services.obs import event as obs_event
from tools.gating import claim_tool_slot


def _gate(tool_name: str):
    """Private-mode + user + rate check, or (None, error)."""
    if auth_mode() != "private":
        obs_event("ratelimit.deny", action="code", tool=tool_name, reason="open_mode")
        return None, (
            f"STATUS=DENIED tool={tool_name}: code execution is disabled "
            "in open mode. Set PLUTO_AUTH_MODE=private (trusted/owner use only)."
        )
    return claim_tool_slot(tool_name, "code", "code-execution")


@tool
def run_python(code: str) -> str:
    """Run Python code in a sandbox for pure computation.

    Use for arithmetic, data wrangling of small inline values, string
    manipulation, and algorithm checks. print() to return output.
    Sandbox: no imports, no files, no network, no `while` loops (use
    `for` with range()), no private/dunder access. Private mode only.

    Args:
        code: Python source (max 4000 chars). Top-level statements;
            no `if __name__` guard needed.

    Returns:
        Printed output, or a structured failure marker (never silent).
    """
    _user_id, err = _gate("run_python")
    if _user_id is None:
        return err
    result = codeexec.execute(str(code or ""))
    if "error" in result:
        kind = "INVALID" if result.get("invalid") else "FAILED"
        return f"STATUS={kind} tool=run_python: {result['error']}"
    out = str(result.get("output", ""))
    if not out.strip():
        return "STATUS=EMPTY tool=run_python: code ran with no output (use print())."
    if result.get("truncated"):
        out += f"\n[Note: output truncated to {MAX_PYTHON_OUTPUT_CHARS} chars.]"
    return out
