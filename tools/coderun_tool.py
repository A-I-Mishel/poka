"""run_code: real multi-language execution inside the workspace.

Private-mode only (PLUTO_AUTH_MODE=private): real subprocess execution
is the biggest security surface in the toolbox, so open mode is denied
outright. In private mode commands run with cwd locked to the user's
workspace, shell=False, secret-stripped env, timeout + output caps.

Two modes:
- file mode: run_code(file="main.py") runs a workspace file.
- inline mode: run_code(language="python", code="print(1)") writes
  workspace/_snippet.<ext> then runs it (great for quick checks).

Runnable: py, js/mjs/cjs, ts/mts (Node 24 type-stripping), java
(single-file), go, c, cpp, rs, php, rb — when the toolchain exists on
the host, else an honest STATUS=FAILED naming the missing runtime.
"""

from langchain_core.tools import tool

from services import coderun
from services.identity import auth_mode
from services.limits import MAX_CODE_OUTPUT_CHARS
from services.obs import event as obs_event
from tools.gating import claim_tool_slot


def _gate(tool_name: str):
    if auth_mode() != "private":
        obs_event("ratelimit.deny", action="code", tool=tool_name,
                  reason="open_mode")
        return None, (
            f"STATUS=DENIED tool={tool_name}: code execution is disabled "
            "in open mode. Set PLUTO_AUTH_MODE=private (trusted/owner use only)."
        )
    return claim_tool_slot(tool_name, "code", "code-execution")


def _format(res: dict, tool_name: str) -> str:
    if "error" in res and "output" not in res:
        kind = "INVALID" if res.get("invalid") else "FAILED"
        return f"STATUS={kind} tool={tool_name}: {res['error']}"
    out = str(res.get("output", ""))
    code = res.get("exit_code", 0)
    dur = res.get("duration_s", "")
    tail = f"\n[exit={code}" + (f" in {dur}s]" if dur != "" else "]")
    if res.get("timeout"):
        head = f"STATUS=FAILED tool={tool_name}: {res.get('error', 'timed out')}"
        return head + (f"\nPartial output:\n{out}" if out.strip() else "")
    if "error" in res:
        # Compile failure with captured output.
        return f"STATUS=FAILED tool={tool_name}: {res['error']}"
    if not out.strip():
        return f"STATUS=EMPTY tool={tool_name}: process exited {code} with no output.{tail}"
    note = ""
    if res.get("truncated"):
        note = f"\n[Note: output truncated to {MAX_CODE_OUTPUT_CHARS} chars.]"
    if int(code) != 0:
        return f"STATUS=FAILED tool={tool_name}: exit {code}.{tail}\n{out}{note}"
    return f"{out}{tail}{note}"


@tool
def run_code(file: str = "", language: str = "", code: str = "",
             cli_args: str = "") -> str:
    """Run real code in your private workspace. Private mode only.

    File mode: run_code(file="main.py") — runs a file you created with
    workspace_write. Inline mode: run_code(language="python",
    code="print(2+2)") — writes _snippet.<ext> then runs it.

    Languages (when installed on host): python, node (js/mjs/cjs/ts),
    java, go, c, cpp, rust, php, ruby. Missing toolchains report
    honestly instead of faking output. cwd is the workspace; network
    and secrets are NOT isolated — trusted-owner use only.

    Args:
        file: Workspace-relative file to run (e.g. "main.py").
        language: Inline language (e.g. "python", "node", "java").
        code: Inline source to run (needs language).
        cli_args: Space-separated CLI args (max 20, passed literally).

    Returns:
        Program output with exit code, or a STATUS= marker.
    """
    user_id, err = _gate("run_code")
    if user_id is None:
        return err
    f = str(file or "").strip()
    lang = str(language or "").strip()
    src = str(code or "")
    if f:
        res = coderun.execute_file(user_id, f, str(cli_args or ""))
        return _format(res, "run_code")
    if lang and src.strip():
        if str(cli_args or "").strip():
            return ("STATUS=INVALID tool=run_code: cli_args are file-mode only "
                    "(run_code(file=...)). Re-run without cli_args or put the file "
                    "in the workspace first; nothing was executed.")
        res = coderun.execute_inline(user_id, lang, src)
        return _format(res, "run_code")
    return ("STATUS=INVALID tool=run_code: provide file=\"main.py\" OR "
            "language+code (e.g. language=\"python\", code=\"print(1)\"). "
            "Create files with workspace_write first.")
