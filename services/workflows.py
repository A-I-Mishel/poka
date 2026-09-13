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
- `confirm` must be a real boolean at save time: a templated string
  would be truthy and forge standing permission for writes.
- Any other `{{...}}` shape is rejected (typos fail loudly at save,
  never silently at run).
- Post-render args are length-capped; overlong renders fail the step
  instead of silently truncating semantics (SQL/code must never be
  cut mid-statement).

Persistence lives on UserStore (services.storage, mirroring briefs);
execution lives in agent.workflows (needs the agent tool funnel).
"""

import re
from typing import Any, Dict, List, Optional, Tuple

# {{input}} or {{steps.N.output}}, tolerant of inner whitespace.
_TEMPLATE_RE = re.compile(r"\{\{\s*(input|steps\.(\d+)\.output)\s*\}\}")
# Any {{...}} at all (used to reject unknown shapes).
_ANY_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}")

# Tools that may never appear in a pipeline (see module docstring).
BLOCKED_PIPELINE_TOOLS = frozenset({"send_gmail"})

# Args that must be static: no {{steps.N.output}} templates. These are
# code, statements, identifiers, or tool routing — templating untrusted
# step output into them is injection (SQL/code), recipient confusion
# (`to`), or destructive mis-targeting (`event_id`/`message_id`).
# `draft_id` takes no templated input today but is locked for consistency.
STATIC_ARGS = frozenset({
    "code", "sql", "table", "upload_id", "server", "tool",
    "event_id", "message_id", "to", "draft_id",
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
        MAX_WORKFLOW_ARG_CHARS,
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
        if key == "confirm" and not isinstance(value, bool):
            raise ValueError(
                f"Workflow {where}: 'confirm' must be true/false "
                "(templated strings would be truthy and forge permission)."
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
        clean_args[key] = value
    return {"tool": tool, "args": clean_args}


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
        rendered[key] = text
    return rendered, None
