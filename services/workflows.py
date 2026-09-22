"""Saved workflow pipelines: validation and template rendering.

A workflow is an owner-saved FIXED sequence of tool calls (no LLM
planning at run time): [{"tool": name, "args": {...}}, ...]. Steps run
in order; each step's string args may embed `{{input}}` (the run-time
input, owner-supplied) and `{{steps.N.output}}` (an EARLIER step's
reported output, untrusted tool DATA).

Security rules (enforced here, so every entry point inherits them):
- `send_gmail` is blocked entirely: pipelines run non-interactively,
  and email exfiltrates off-device silently.
- Code/identifier args (`code`, `sql`, `table`, `upload_id`, `server`,
  `tool`, `event_id`, `message_id`, `to`, `draft_id`) must be static:
  no `{{steps.N.output}}` templates (`{{input}}` is allowed — it is
  owner-supplied at run time, like the chat box). This closes
  template-driven code/SQL injection and identifier confusion
  (e.g. untrusted step output becoming a Gmail recipient or a
  calendar-delete target) from untrusted step output.
- `confirm`/`approval_token` args are rejected outright: approvals are
  interactive-only and saved runs cannot approve, so pipelines can never
  authorize destructive actions.
- Any other `{{...}}` shape is rejected (typos fail loudly at save,
  never silently at run).
- Post-render args are length-capped; overlong renders fail the step
  instead of silently truncating semantics (SQL/code must never be
  cut mid-statement).

Persistence lives on UserStore (services.storage, mirroring briefs);
execution lives in agent.workflows (needs the agent tool funnel).
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

# {{input}} or {{steps.N.output}}, tolerant of inner whitespace.
logger = logging.getLogger(__name__)
_TEMPLATE_RE = re.compile(r"\{\{\s*(input|steps\.(\d+)\.output)\s*\}\}")
# Any {{...}} at all (used to reject unknown shapes).
_ANY_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}")

# Tools that may never appear in a pipeline (see module docstring).
BLOCKED_PIPELINE_TOOLS = frozenset({"send_gmail"})

# Table identifiers: single SQLite table, no schema qualification or
# quoting — single file per user, ATTACH rejected at exec. Rejects
# `db.table`, `"table"`, `table; DROP`, etc. with Unsafe table name.
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

# Args that must be static: no {{steps.N.output}} templates. These are
# code, statements, identifiers, or tool routing — templating untrusted
# step output into them is injection (SQL/code), recipient confusion
# (`to`), or destructive mis-targeting (`event_id`/`message_id`).
# `draft_id` takes no templated input today but is locked for consistency.
# Workspace/code-runner args (path/file/content/language/cli_args) are
# code + identifiers too: untrusted step output must never become
# executed code or a write target without owner review.
STATIC_ARGS = frozenset({
    "code", "sql", "table", "upload_id", "server", "tool",
    "event_id", "message_id", "to", "draft_id",
    "path", "file", "content", "language", "cli_args", "args",
})


def _template_refs(text: str) -> Tuple[List[int], bool, bool]:
    """Parse template refs in text.

    Returns (step_indexes, has_input, has_unknown): step_indexes lists
    every N in `{{steps.N.output}}`; has_input flags `{{input}}`;
    has_unknown flags any other `{{...}}` shape.
    """
    indexes: List[int] = []
    has_input = False
    spans: List[Tuple[int, int]] = []
    for match in _TEMPLATE_RE.finditer(text):
        spans.append(match.span())
        if match.group(1) == "input":
            has_input = True
        else:
            indexes.append(int(match.group(2)))
    has_unknown = any(
        not any(start <= match.start() and match.end() <= end for start, end in spans)
        for match in _ANY_TEMPLATE_RE.finditer(text)
    )
    return indexes, has_input, has_unknown


def validate_workflow(
    name: Any,
    steps: Any,
    description: Any = "",
    known_tools: Optional[Any] = None,
) -> Tuple[str, str, List[Dict[str, Any]]]:
    """Validate a workflow definition; returns (name, description, steps).

    Steps are cleaned to [{"tool": str, "args": {str: scalar}}].
    Raises ValueError with a human-readable reason for anything invalid.
    known_tools (e.g. TOOL_MAP keys) additionally rejects unknown tool
    names; None skips that check (shape-only validation).
    """
    from services.limits import (
        MAX_WORKFLOW_DESC_CHARS,
        MAX_WORKFLOW_NAME_CHARS,
        MAX_WORKFLOW_STEPS,
    )

    if not isinstance(name, str) or not name.strip():
        raise ValueError("Workflow name must not be empty.")
    if len(name.strip()) > MAX_WORKFLOW_NAME_CHARS:
        raise ValueError(
            f"Workflow name is limited to {MAX_WORKFLOW_NAME_CHARS} characters."
        )
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ValueError("Workflow description must be a string.")
    if len(description) > MAX_WORKFLOW_DESC_CHARS:
        raise ValueError(
            f"Workflow description is limited to {MAX_WORKFLOW_DESC_CHARS} characters."
        )
    if not isinstance(steps, list) or not steps:
        raise ValueError("Workflow needs at least one step.")
    if len(steps) > MAX_WORKFLOW_STEPS:
        raise ValueError(
            f"Workflows are limited to {MAX_WORKFLOW_STEPS} steps."
        )
    cleaned: List[Dict[str, Any]] = []
    for pos, raw in enumerate(steps):
        cleaned.append(_validate_step(raw, pos, len(steps), known_tools))
    return name.strip(), description.strip(), cleaned


def _validate_step(
    raw: Any,
    pos: int,
    total: int,
    known_tools: Optional[Any],
) -> Dict[str, Any]:
    """Validate one step dict; raises ValueError. See validate_workflow."""
    from services.limits import MAX_WORKFLOW_ARG_CHARS

    where = f"step {pos + 1}"
    if not isinstance(raw, dict):
        raise ValueError(f"Workflow {where} must be an object.")
    tool = raw.get("tool", "")
    if not isinstance(tool, str) or not tool.strip():
        raise ValueError(f"Workflow {where} needs a tool name.")
    tool = tool.strip()
    if tool in BLOCKED_PIPELINE_TOOLS:
        raise ValueError(
            f"Workflow {where}: tool '{tool}' is not allowed in pipelines."
        )
    if known_tools is not None and tool not in known_tools:
        raise ValueError(f"Workflow {where}: unknown tool '{tool}'.")
    args = raw.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError(f"Workflow {where}: args must be an object.")
    clean_args: Dict[str, Any] = {}
    for key, value in args.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"Workflow {where}: arg names must be strings.")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise ValueError(
                f"Workflow {where}: arg '{key}' must be a string, number, "
                "boolean, or null (no nested objects)."
            )
        if key in ("confirm", "approval_token"):
            raise ValueError(
                f"Workflow {where}: '{key}' is not allowed in pipelines "
                "(approvals are interactive-only; saved runs cannot approve)."
            )
        if isinstance(value, str):
            if len(value) > MAX_WORKFLOW_ARG_CHARS:
                raise ValueError(
                    f"Workflow {where}: arg '{key}' exceeds "
                    f"{MAX_WORKFLOW_ARG_CHARS} characters."
                )
            indexes, _has_input, has_unknown = _template_refs(value)
            if has_unknown:
                raise ValueError(
                    f"Workflow {where}: arg '{key}' has an unknown "
                    "{{...}} template (only {{input}} and "
                    "{{steps.N.output}} are supported)."
                )
            for n in indexes:
                if n >= total:
                    raise ValueError(
                        f"Workflow {where}: arg '{key}' references "
                        f"{{{{steps.{n}.output}}}} but the workflow has "
                        f"only {total} step(s)."
                    )
                if n >= pos:
                    raise ValueError(
                        f"Workflow {where}: arg '{key}' references a later "
                        "step (only earlier steps' output is available)."
                    )
            if key in STATIC_ARGS and indexes:
                raise ValueError(
                    f"Workflow {where}: arg '{key}' must be static "
                    "(no {{steps.N.output}} templates in code, SQL, "
                    "identifiers, or tool routing)."
                )
            # Table identifiers are always allowlisted — even fully static
            # values must match SQLite identifier syntax (no db.table,
            # quoting, or separators). Templated tables are validated again
            # after render in render_args (untrusted input could arrive via
            # {{input}} at run time).
            if key == "table" and isinstance(value, str):
                _v = str(value).strip()
                if _v and not ("{{" in _v and "}}" in _v) and not _TABLE_RE.match(_v):
                    raise ValueError(
                        f"Workflow {where}: arg 'table' has Unsafe table name."
                    )
        clean_args[key] = value
    return {"tool": tool, "args": clean_args}


def validate_workflow_untrusted(workflow: Dict[str, Any]) -> None:
    """Reject {{input}} in STATIC_ARGS for untrusted/chained runs (never raises silently).

    Owner-saved workflows may use {{input}} in code/sql/table (docstring
    contract, tested in test_workflows.py). When the run-time input is
    untrusted or chained from another step/output, call this before
    execution to require fully static code/SQL/identifiers. Raises
    ValueError on violation.
    """
    try:
        steps = (workflow or {}).get("steps", []) if isinstance(workflow, dict) else []
        for pos, raw in enumerate(steps or []):
            if not isinstance(raw, dict):
                continue
            args = raw.get("args", {}) or {}
            if not isinstance(args, dict):
                continue
            for key, value in args.items():
                if not isinstance(value, str) or key not in STATIC_ARGS:
                    continue
                try:
                    _idx, _has_input, _unknown = _template_refs(value)
                except Exception:
                    logger.debug("static-arg template probe failed; skipping key", exc_info=True)
                    continue
                if _has_input:
                    raise ValueError(
                        f"Workflow step {pos + 1}: arg '{key}' must be fully static "
                        "for untrusted input (no {{input}} in code, SQL, identifiers)."
                    )
    except ValueError:
        raise
    except Exception:
        return


def render_args(
    args: Dict[str, Any],
    run_input: str,
    prior_outputs: List[str],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Resolve templates in one step's args.

    Returns (rendered_args, None) or ({}, error). Only strings are
    touched; rendered strings are re-capped (overlong renders fail the
    step rather than truncating semantics).
    """
    from services.limits import MAX_WORKFLOW_ARG_CHARS

    rendered: Dict[str, Any] = {}
    for key, value in args.items():
        if not isinstance(value, str):
            rendered[key] = value
            continue
        try:
            text = _TEMPLATE_RE.sub(
                lambda m: run_input
                if m.group(1) == "input"
                else prior_outputs[int(m.group(2))],
                value,
            )
        except (IndexError, ValueError):
            return {}, f"arg '{key}' references unavailable step output"
        if _ANY_TEMPLATE_RE.search(text):
            return {}, f"arg '{key}' has an unresolvable template"
        if len(text) > MAX_WORKFLOW_ARG_CHARS:
            return {}, (
                f"arg '{key}' exceeds {MAX_WORKFLOW_ARG_CHARS} characters "
                "after template rendering"
            )
        if key == "table":
            if not _TABLE_RE.match(str(text).strip()):
                return {}, "arg 'table' has Unsafe table name"
        rendered[key] = text
    return rendered, None
