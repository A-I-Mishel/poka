"""Workflow runner: execute saved fixed pipelines deterministically.

No LLM planning happens here — steps run in order through the same
tool funnel as the agent loop (agent.toolrun._execute_tool_call), so
every step gets budget charging, wall-clock timeouts, and STATUS
markers. The first step that does not report STATUS=OK stops the run
(referencing a failed step's output would cascade garbage); wall-clock
or tool-budget exhaustion stops it as partial.

Template values are untrusted DATA (prior step tool output): dangerous
sinks are already restricted at save time (services.workflows), and
rendered args are re-capped there too.
"""

import logging
from typing import Any, Dict, List, Optional

from agent.budget import BudgetExhausted, RequestBudget
from agent.toolrun import TOOL_MAP, _execute_tool_call
from services import workflows as workflows_svc
from services.context import get_current_user_id, get_limit_key, set_current_user_id, set_limit_key
from services.limits import MAX_WORKFLOW_ARG_CHARS, MAX_WORKFLOW_INPUT_CHARS
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter

logger = logging.getLogger(__name__)


def run_workflow(
    workflow: Any,
    run_input: Any = "",
    user_id: Optional[str] = None,
    limit_key: Optional[str] = None,
    budget: Optional[RequestBudget] = None,
) -> Dict[str, Any]:
    """Run one saved pipeline; never raises (failures are data).

    Args:
        workflow: The stored record (id/name/steps) from UserStore.
        run_input: Owner-supplied `{{input}}` text (capped).
        user_id/limit_key: Bound for tool user-context and the
            workflow rate check (defaults: current thread context).
        budget: Optional RequestBudget (a fresh one is built when
            omitted, sized to cover every step).

    Returns:
        {"workflow_id", "name", "status" ("ok"/"failed"/"partial"),
         "steps": [{"index","tool","ok","output"}], "tools_used": [...],
         "error": str, "input_truncated": bool}.
    """
    wid = workflow.get("id", "") if isinstance(workflow, dict) else ""
    name = workflow.get("name", "") if isinstance(workflow, dict) else ""
    steps = workflow.get("steps", []) if isinstance(workflow, dict) else []

    def _result(status: str, done: List[Dict[str, Any]],
                used: List[str], error: str = "",
                truncated: bool = False) -> Dict[str, Any]:
        return {
            "workflow_id": str(wid or ""),
            "name": str(name or ""),
            "status": status,
            "steps": done,
            "tools_used": list(used),
            "error": str(error or ""),
            "input_truncated": bool(truncated),
        }

    try:
        bound_user = user_id if user_id else get_current_user_id()
        bound_limit = limit_key or get_limit_key() or bound_user
        if bound_user:
            # Tools (and their worker threads) read context off the
            # calling thread: re-bind explicitly so runs work from any
            # thread, mirroring _run_tool_with_context.
            set_current_user_id(bound_user)
            set_limit_key(bound_limit or bound_user)
        verdict = get_rate_limiter().check(bound_limit or bound_user or "anonymous", "workflow")
        if not verdict.allowed:
            obs_event("ratelimit.deny", action="workflow", user=str(bound_user or ""),
                      retry_after_s=round(verdict.retry_after, 1))
            return _result(
                "failed", [], [],
                f"Workflow rate limit exceeded, retry in {verdict.retry_after:.0f}s.",
            )
        if not isinstance(steps, list) or not steps:
            return _result("failed", [], [], "Workflow has no steps.")
        if not isinstance(workflow, dict):
            return _result("failed", [], [], "Invalid workflow record.")

        text_input = run_input if isinstance(run_input, str) else str(run_input or "")
        input_truncated = False
        if len(text_input) > MAX_WORKFLOW_INPUT_CHARS:
            text_input = text_input[:MAX_WORKFLOW_INPUT_CHARS]
            input_truncated = True

        # Pre-flight: every tool must resolve BEFORE anything executes,
        # so a typo on step 4 cannot run steps 1-3 as a side effect.
        for pos, step in enumerate(steps):
            tool_name = step.get("tool", "") if isinstance(step, dict) else ""
            if tool_name not in TOOL_MAP:
                return _result(
                    "failed", [], [],
                    f"Step {pos + 1}: unknown tool '{tool_name}'.",
                    input_truncated,
                )

        own_budget = budget if budget is not None else RequestBudget()
        # Use a local max_tools cap without mutating the caller's budget.
        # Create a fresh budget with the needed capacity, preserving caller's
        # deadline and other limits, only raising max_tools if needed.
        if budget is not None and budget.max_tools < len(steps):
            own_budget = RequestBudget(
                max_llm=budget.max_llm,
                max_tools=len(steps),
                max_search=budget.max_search,
                max_reflect=budget.max_reflect,
                max_plan=budget.max_plan,
                max_rounds=budget.max_rounds,
                deadline=budget.deadline,
            )

        done: List[Dict[str, Any]] = []
        used: List[str] = []
        prior_outputs: List[str] = []
        for pos, step in enumerate(steps):
            try:
                own_budget.check_time()
            except BudgetExhausted as e:
                return _result("partial", done, used, str(e)[:200], input_truncated)
            tool_name = step["tool"]
            rendered, render_error = workflows_svc.render_args(
                step.get("args", {}) if isinstance(step.get("args", {}), dict) else {},
                text_input,
                prior_outputs,
            )
            if render_error is not None:
                done.append({"index": pos, "tool": tool_name, "ok": False,
                             "output": f"STATUS=FAILED tool={tool_name}: {render_error}."})
                return _result("failed", done, used,
                               f"Step {pos + 1} ({tool_name}): {render_error}.",
                               input_truncated)
            try:
                output = _execute_tool_call(
                    {"name": tool_name, "args": rendered}, own_budget
                )
            except BudgetExhausted as e:
                return _result("partial", done, used, str(e)[:200], input_truncated)
            except Exception as e:
                logger.warning("workflow step failed: %s", e)
                output = f"STATUS=FAILED tool={tool_name}: {str(e)[:200]}"
            output = str(output or "")
            ok = output.startswith("STATUS=OK")
            done.append({"index": pos, "tool": tool_name, "ok": ok, "output": output})
            if tool_name not in used:
                used.append(tool_name)
            # Template source = reported output, capped (deterministic:
            # later steps see exactly what the run reports).
            prior_outputs.append(output[:MAX_WORKFLOW_ARG_CHARS])
            if not ok:
                return _result(
                    "failed", done, used,
                    f"Step {pos + 1} ({tool_name}) did not succeed; "
                    "pipeline stopped.",
                    input_truncated,
                )
        return _result("ok", done, used, "", input_truncated)
    except Exception as e:
        logger.warning("workflow run failed: %s", e)
        return _result("failed", [], [], f"Workflow run failed: {str(e)[:200]}")
