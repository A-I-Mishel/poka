"""Tool execution: single funnel plus the main tool loop.

Every model-requested tool call flows through _execute_tool_call, which
charges the request budget, bounds wall-clock time, re-binds the
submitting request's user (worker threads do not inherit contextvars),
and returns explicit STATUS markers so the model can distinguish success
from failure.

run_tool_loop keeps history clean for Gemini 3.x (no functionCall
blocks ever go back): tool results return inside fresh human messages.
"""

import json as _json
import re as _re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from services.context import get_current_user_id, get_limit_key, set_limit_key, set_current_user_id
from services.context_budget import CTX_HISTORY_TOKENS, CTX_MEMORY_TOKENS, fit_history, fit_text
from services.limits import (
    MAX_EXTERNAL_TOKENS,
    MAX_QUERY_CHARS,
    MAX_TOOL_RESULT_TOKENS,
    MAX_TOOL_ROUNDS,
    SYNTHESIS_TIMEOUT_SECONDS,
    TOOL_TIMEOUT_SECONDS,
)
from services.obs import (
    record_tool_execution_mode,
    timed as obs_timed,
    trace_tool_call,
)
from services.storage import MAX_SOURCES, clean_source_record
from services.tokens import count_tokens, truncate_tokens
from tools import web_search, create_pptx, build_presentation, create_docx, build_document, create_pdf, create_markdown, create_doc, create_html, read_output, read_pdf, read_pdf_page, read_document, analyze_csv, csv_inspect, check_logic, search_documents, search_gmail, read_gmail, create_gmail_draft, send_gmail, list_calendar_events, create_calendar_event, delete_calendar_event, list_tables, describe_table, query_database, import_csv_table, execute_sql, run_python, workspace_list, workspace_read, workspace_write, workspace_delete, run_code, list_mcp_tools, call_mcp_tool
from tools.search_tool import extract_cited_sources

from agent.budget import BudgetExhausted, RequestBudget, TurnCancelled
from agent.cascade import (
    _record_tier_failure,
    _record_tier_success,
    classify_provider_error,
)
from agent.executor import TokenStream, _call_bounded

import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.prompts import STRICT_GROUNDING_PARAGRAPH, _as_text, _build_system_prompt, is_strict_tier, strip_internal_reasoning

tools: List[Any] = [web_search, search_documents, search_gmail, read_gmail, create_gmail_draft, send_gmail, list_calendar_events, create_calendar_event, delete_calendar_event, list_tables, describe_table, query_database, import_csv_table, execute_sql, run_python, workspace_list, workspace_read, workspace_write, workspace_delete, run_code, list_mcp_tools, call_mcp_tool, create_pptx, build_presentation, create_docx, build_document, create_pdf, create_markdown, create_doc, create_html, read_output, read_pdf, read_pdf_page, read_document, analyze_csv, csv_inspect, check_logic]
TOOL_MAP: Dict[str, Any] = {t.name: t for t in tools}

# Tool classification: read-only tools can run in parallel; mutating tools must run serially.
# Read-only: no vault writes, no external side effects, idempotent reads.
_READ_ONLY_TOOLS = frozenset({
    "web_search", "search_documents", "search_gmail", "read_gmail",
    "list_calendar_events", "list_tables", "describe_table", "query_database",
    "workspace_list", "workspace_read", "read_output", "read_pdf",
    "read_pdf_page", "read_document", "analyze_csv", "csv_inspect",
    "list_mcp_tools", "check_logic",
})

# Mutating tools: vault writes, external side effects, non-idempotent.
_MUTATING_TOOLS = frozenset({
    "create_gmail_draft", "send_gmail", "create_calendar_event", "delete_calendar_event",
    "import_csv_table", "execute_sql", "run_python", "workspace_write",
    "workspace_delete", "run_code", "call_mcp_tool",
    "create_pptx", "build_presentation", "create_docx", "build_document",
    "create_pdf", "create_markdown", "create_doc", "create_html",
})

def is_read_only_tool(name: str) -> bool:
    """Check if a tool is read-only (can run in parallel)."""
    return name in _READ_ONLY_TOOLS

def is_mutating_tool(name: str) -> bool:
    """Check if a tool is mutating (must run serially)."""
    return name in _MUTATING_TOOLS


_BRACKET_CALL_RE = _re.compile(
    r"\[\s*tool\s*call\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(([^]\[]*)\)\s*\]",
    _re.IGNORECASE,
)
_BRACKET_ARG_RE = _re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([0-9]+))")


def _fallback_bracket_calls_from_text(text: str) -> List[Dict[str, Any]]:
    """Parse "[Tool call: name(k=v, ...)]" leaks into real tool calls.

    Some tiers narrate actions ("[Tool call: read_document(upload_id=...)]")
    instead of emitting tool_calls. Only known READ-ONLY tools with scalar
    args (upload_id/page/query-style) are accepted; mutating tools parsed
    from text are never executed (approvals are interactive-only).
    Anything else is ignored. Stdlib only, never raises.
    """
    candidates: List[Dict[str, Any]] = []
    try:
        for m in _BRACKET_CALL_RE.finditer(text or ""):
            name = str(m.group(1) or "").strip()
            if not name or name not in TOOL_MAP or not is_read_only_tool(name):
                continue
            args: Dict[str, Any] = {}
            for am in _BRACKET_ARG_RE.finditer(m.group(2) or ""):
                key = str(am.group(1) or "").strip()
                val: Any = am.group(2) if am.group(2) is not None else (
                    am.group(3) if am.group(3) is not None else am.group(4))
                if key and isinstance(val, str):
                    args[key] = val[:500]
            candidates.append({"name": name, "args": args})
            if len(candidates) >= 4:
                break
    except Exception:
        pass
    return candidates


def _fallback_tool_calls_from_text(text: str) -> List[Dict[str, Any]]:
    """Parse JSON tool calls leaked as text (model wrote JSON instead of tool_calls).

    Free tiers often emit {"tool":"read_document","upload_id":"..."} as
    content; the structured tool_calls list is then empty and the raw
    JSON leaks to the user. This extracts it so it can be executed
    normally. Also handles "[Tool call: name(args)]" narration. Mutating
    tools parsed from text are never executed (read-only only).
    Stdlib only, never raises.
    """
    if not text:
        return []
    found = _fallback_bracket_calls_from_text(text)
    if "{" not in text:
        return found[:4]
    if '"tool"' not in text and '"name"' not in text:
        return found[:4]
    # ponytail: brace-counting extractor for leaked JSON - upgrade to
    # full json repair only if free-tier models start emitting broken JSON
    candidates: List[Dict[str, Any]] = []
    for m in _re.finditer(r'\{\s*"(?:tool|name)"\s*:', text):
        start = m.start()
        depth = 0
        end = -1
        for i in range(start, min(len(text), start + 2000)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            continue
        snippet = text[start : end + 1]
        # strip code fences if wrapped
        snippet = snippet.strip().strip("`")
        try:
            obj = _json.loads(snippet)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        name = str(obj.get("tool") or obj.get("name") or "").strip()
        if not name or name not in TOOL_MAP or not is_read_only_tool(name):
            continue
        args = obj.get("args")
        if not isinstance(args, dict):
            # flat form: {"tool":"read_document","upload_id":"..."}
            args = {k: v for k, v in obj.items() if k not in ("tool", "name", "args")}
            if not isinstance(args, dict):
                args = {}
        # keep only string-keyed args
        args = {str(k): v for k, v in args.items()}
        candidates.append({"name": name, "args": args})
        if len(found) + len(candidates) >= 4:
            break
    return (found + candidates)[:4]


def _run_tool_with_context(user_id: Any, tool: Any, args: Dict[str, Any], limit_key: Any = None) -> Any:
    """Invoke a tool with the submitting request's user bound.

    Worker threads do not inherit contextvars, so the user ID (and the
    rate-limit identity) captured on the calling thread are explicitly
    restored here. Without this, every tool would see "no user" and
    deny vault access, and limits would fall back to per-tool-call keys.
    """
    if user_id is not None:
        set_current_user_id(user_id)
    if limit_key is not None:
        set_limit_key(limit_key)
    return tool.invoke(args)


def _result_status(text: str) -> str:
    """Map a raw tool result to an obs status (metadata only)."""
    head = text[:24]
    for marker in ("STATUS=OK", "STATUS=EMPTY", "STATUS=FAILED", "STATUS=INVALID", "STATUS=DENIED", "STATUS=DEGRADED"):
        if head.startswith(marker):
            return marker.split("=", 1)[1].lower()
    return "empty" if not text.strip() else "ok"


def _execute_tool_call(tool_call: Any, budget: Optional[RequestBudget] = None) -> str:
    """Execute one model-requested tool call with time + budget bounds.

    Returns explicit STATUS markers (OK/EMPTY/FAILED/INVALID/DENIED) so the
    model can distinguish success from failure. Result text is capped to
    the per-result token budget. Never raises for tool problems, but
    BudgetExhausted propagates so the loop stops instead of spinning.
    """
    if isinstance(tool_call, dict):
        name: str = str(tool_call.get("name", ""))
        args: Dict[str, Any] = dict(tool_call.get("args", {}) or {})
    else:
        name = str(getattr(tool_call, "name", ""))
        raw_args = getattr(tool_call, "args", {}) or {}
        args = dict(raw_args) if isinstance(raw_args, dict) else {}
    tool = TOOL_MAP.get(name)
    if tool is None:
        return f"STATUS=INVALID tool call: unknown tool '{name}'."
    if budget is not None:
        # May raise BudgetExhausted: intentional, stops the loop upstream.
        budget.count_tool(is_search=(name == "web_search"))
    try:
        user_id = get_current_user_id()
        limit_key = get_limit_key()
        with obs_timed(f"tool.{name}") as rec:
            out = _call_bounded(
                lambda: _run_tool_with_context(user_id, tool, args, limit_key),
                TOOL_TIMEOUT_SECONDS,
                f"Tool {name}",
            )
        text = str(out)
        rec["status"] = _result_status(text)
        if text.startswith("STATUS="):
            return f"[{name}] {text}"
        if not text.strip():
            return f"STATUS=EMPTY tool={name}: the tool returned no content."
        if count_tokens(text) > MAX_TOOL_RESULT_TOKENS:
            text = truncate_tokens(text, MAX_TOOL_RESULT_TOKENS)
        if budget is not None:
            budget.external_tokens += count_tokens(text)
        return f"STATUS=OK tool={name}\n<untrusted_tool_output>\n{text}\n</untrusted_tool_output>"
    except TimeoutError as e:
        return f"STATUS=FAILED tool={name}: {e}"
    except Exception as e:
        return f"STATUS=FAILED tool={name}: {str(e)[:300]}"


def _has_read_only_tools(tool_calls: List[Any]) -> bool:
    """Check if all tool calls are read-only (can run in parallel)."""
    for tc in tool_calls:
        if isinstance(tc, dict):
            name = str(tc.get("name", ""))
        else:
            name = str(getattr(tc, "name", ""))
        if not is_read_only_tool(name):
            return False
    return True


def _execute_tool_calls_parallel(
    tool_calls: List[Any],
    budget: Optional[RequestBudget] = None,
    max_workers: int = 4,
) -> List[str]:
    """Execute multiple read-only tool calls in parallel.

    Only read-only tools are parallelized; mutating tools run serially.
    Returns results in the same order as input tool_calls.
    """
    if not tool_calls:
        return []

    # Separate read-only and mutating tools
    read_only = []
    mutating = []
    for i, tc in enumerate(tool_calls):
        if isinstance(tc, dict):
            name = str(tc.get("name", ""))
        else:
            name = str(getattr(tc, "name", ""))
        if is_read_only_tool(name):
            read_only.append((i, tc))
        else:
            mutating.append((i, tc))

    results = [None] * len(tool_calls)

    # Execute read-only tools in parallel
    if read_only:
        # Capture the submitting request's identity HERE (agent thread):
        # pool threads do not inherit contextvars, so capturing inside
        # _execute_tool_call (which runs in the worker) always yields None
        # and every user-scoped read tool denies with "no user context".
        caller_user_id = get_current_user_id()
        caller_limit_key = get_limit_key()

        def _call_with_caller_context(tc: Any) -> str:
            if caller_user_id is not None:
                set_current_user_id(caller_user_id)
            if caller_limit_key is not None:
                set_limit_key(caller_limit_key)
            return _execute_tool_call(tc, budget)

        with ThreadPoolExecutor(max_workers=min(max_workers, len(read_only))) as executor:
            future_to_idx = {
                executor.submit(_call_with_caller_context, tc): idx
                for idx, tc in read_only
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = f"STATUS=FAILED tool=parallel: {e}"

    # Execute mutating tools serially (preserve order)
    for idx, tc in mutating:
        try:
            results[idx] = _execute_tool_call(tc, budget)
        except Exception as e:
            results[idx] = f"STATUS=FAILED tool=serial: {e}"

    return results


def _note_tier_failure(tier_name: Any, error: Any) -> None:
    """Cool a tier down after it fails mid-task (never raises).

    Unknown/empty names are ignored. Classification decides the
    cool-down length; our own budget exhaustion is never recorded
    here (callers re-raise it before reaching this helper).
    """
    if not isinstance(tier_name, str) or not tier_name:
        return
    try:
        _record_tier_failure(tier_name, classify_provider_error(error)[0], error)
    except Exception:
        pass


def run_tool_loop(
    llm_instance: BaseLanguageModel,
    user_input: str,
    chat_history: Sequence[BaseMessage],
    memory_notes: str = "",
    relevant_context: str = "",
    force_web_search: bool = False,
    max_rounds: int = MAX_TOOL_ROUNDS,
    budget: Optional[RequestBudget] = None,
    used_tools: Optional[List[str]] = None,
    used_sources: Optional[List[Dict[str, str]]] = None,
    project_context: str = "",
    llm_provider: Optional[Callable[[], Tuple[str, Any]]] = None,
    tier_trace: Optional[List[str]] = None,
    on_token: Optional[Callable[[str], None]] = None,
    on_reset: Optional[Callable[[], None]] = None,
    final_tier: Optional[List[str]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    request_id: Optional[str] = None,
    cancel: Optional[Callable[[], bool]] = None,
    strict: bool = False,
) -> str:
    """Run one request through an explicit tool loop with clean history.

    Tool results are returned to the model inside fresh human messages so
    the history never contains functionCall blocks (which Gemini 3.x
    rejects without thought_signature). Untrusted tool content is always
    wrapped in <untrusted_tool_output> delimiters. History and memory are
    fitted to token budgets; the current request is never truncated.

    When force_web_search is true, a web search is EXECUTED first (not
    merely suggested) and its results seed the conversation.

    When used_tools is provided, names of tools actually executed during
    this call are appended (deduped, in order) so callers can record
    truthful provenance. Unknown tool names are never recorded.

    When used_sources is provided, structured source records parsed from
    EXECUTED web-search output are appended (deduped by URL, capped).
    Nothing is ever inferred from model-generated text.

    When llm_provider is provided, each round pulls a fresh (tier name,
    model) pair from it instead of reusing llm_instance: a tier that
    dies mid-task is cooled down and the SAME round retries instantly
    on the next live tier, keeping already-collected tool results.
    Without a provider the loop keeps the historical single-tier
    behavior. Successful tiers are appended to tier_trace when given,
    so callers can report which tier actually finished the work.
    BudgetExhausted is never treated as a tier failure and always
    propagates — it is our limit, not the provider's.

    on_token receives cumulative answer text live as model calls
    stream it; on_reset fires before a new call supersedes an earlier
    one in the same turn (tool rounds, final synthesis), so consumers
    never concatenate stale text with fresh text. Both default to
    None (historical silent behavior). A TokenStream instance passed
    as on_token is shared (never re-wrapped) so resets coordinate
    across nested loops.

    on_progress receives one lightweight status line per tool round
    (tool names only, never prompts or results) so stream consumers
    can show "working" activity while no answer tokens flow yet.
    It never raises into the loop (failures are swallowed).

    When final_tier is provided, the tier that produced the returned
    answer is recorded into it (single-element replace): the round
    tier for direct answers, the last round's tier for final
    synthesis, or the round behind salvaged partial text. Callers use
    it to attribute the answer truthfully after mid-task failover.

    When cancel is provided, it is polled between rounds (and before
    final synthesis): a True return raises TurnCancelled, which aborts
    without synthesis, salvage, tier cooling, or persistence — the
    client went away, so further quota burn is pure waste.
    """
    if budget is None:
        budget = RequestBudget()
    if not request_id:
        try:
            import uuid as _uuid

            request_id = _uuid.uuid4().hex[:8]
        except Exception:
            request_id = "toolloop"
    mem_fit = fit_text(
        (memory_notes.strip() + "\n" + relevant_context.strip()).strip(),
        CTX_MEMORY_TOKENS,
    )
    system_text: str = _build_system_prompt(mem_fit, "", project_context)
    if strict:
        # Weak-tier attempt: strict grounding for the whole turn (a mid-loop
        # failover to a stronger tier simply keeps it — harmless).
        system_text += "\n\n" + STRICT_GROUNDING_PARAGRAPH
    fitted_history, _hist_stats = fit_history(chat_history, CTX_HISTORY_TOKENS)
    messages: List[BaseMessage] = [
        SystemMessage(content=system_text),
        *fitted_history,
    ]
    search_blob_texts: List[str] = []

    def _record_tool(name: Any) -> None:
        """Note an executed tool for provenance (known tools only)."""
        if used_tools is None:
            return
        if not isinstance(name, str):
            return
        if name not in TOOL_MAP:
            return
        if name not in used_tools:
            used_tools.append(name)

    def _record_search_sources(result_text: Any, name: Any) -> None:
        """Collect provenance from EXECUTED web-search output only.

        Parses the tool's own result text with the same extractor the
        answer renderer uses. Model-generated markdown is never parsed
        here (this function only ever sees tool return values).
        """
        if used_sources is None:
            return
        if name != "web_search":
            return
        if not isinstance(result_text, str):
            return
        for parsed in extract_cited_sources(result_text):
            if len(used_sources) >= MAX_SOURCES:
                return
            record = clean_source_record(parsed)
            if record is None:
                continue
            if any(e["url"].lower() == record["url"].lower()
                   for e in used_sources):
                continue
            used_sources.append(record)

    def _note_search(result_text: str) -> None:
        if result_text.startswith("[web_search] STATUS=OK"):
            search_blob_texts.append(result_text)

    def _with_sources(final_text: str) -> str:
        """Append only sources actually returned this request. Never invents."""
        final_text = strip_internal_reasoning(final_text)
        sources: List[Dict[str, str]] = []
        seen_urls = set()
        for blob in search_blob_texts:
            for s in extract_cited_sources(blob):
                if s["url"] and s["url"] in seen_urls:
                    continue
                seen_urls.add(s["url"])
                sources.append(s)
        sources = sources[:6]
        if not sources:
            return final_text
        lines = ["", "Sources consulted:"]
        for i, s in enumerate(sources, start=1):
            label = s["title"] or s["domain"]
            if s["url"]:
                lines.append(f"[{i}] {label} — {s['url']}")
            else:
                lines.append(f"[{i}] {label}")
        return final_text.rstrip() + "\n" + "\n".join(lines) + "\n"

    if force_web_search:
        try:
            forced = _execute_tool_call(
                {"name": "web_search", "args": {"query": user_input[:MAX_QUERY_CHARS]}},
                budget,
            )
            _record_tool("web_search")
            _record_search_sources(forced, "web_search")
        except BudgetExhausted:
            forced = "STATUS=FAILED tool=web_search: search budget exhausted."
        except Exception as e:
            forced = f"STATUS=FAILED tool=web_search: {e}"
        _note_search(forced)
        messages.append(
            HumanMessage(
                content=(
                    "A web search was explicitly requested for the next message. "
                    f"Results (or failure) to use:\n{forced}"
                )
            )
        )
    messages.append(HumanMessage(content=user_input))

    def _filtered_tools(hint: str) -> List[Any]:
        # ponytail: lazy-bind to keep small-context lanes (GitHub 8k) from 400s; expand heuristic when a needed tool is missed
        low = (hint or "").lower()
        base: List[Any] = [web_search, search_documents, workspace_list, workspace_read, check_logic]
        if any(k in low for k in ("pdf", "document", "docx", "pptx", "slide", ".pdf", "upload", "attached", "[content of", "read_document", "read_pdf")):
            base += [read_document, read_pdf, read_pdf_page, read_output, analyze_csv, csv_inspect]
        if any(k in low for k in ("csv", "tsv", "xlsx", "data", "table", "spreadsheet", "database", "sql", "query")):
            base += [analyze_csv, csv_inspect, list_tables, describe_table, query_database, import_csv_table, execute_sql]
        if any(k in low for k in ("presentation", "slides", "pptx", "powerpoint", "essay", "report", "resume", "create", "build")):
            base += [create_pptx, build_presentation, create_docx, build_document, create_pdf, create_markdown, create_doc, create_html, read_output]
        if any(k in low for k in ("code", "python", "workspace", "run_code", "script", "program", "function", "execute")):
            base += [workspace_write, workspace_delete, run_code, run_python, list_mcp_tools, call_mcp_tool]
        if any(k in low for k in ("gmail", "email", "mail", "calendar", "event")):
            base += [search_gmail, read_gmail, create_gmail_draft, send_gmail, list_calendar_events, create_calendar_event, delete_calendar_event]
        # dedupe
        seen = set()
        out: List[Any] = []
        for t in base:
            if getattr(t, "name", "") not in seen:
                seen.add(getattr(t, "name", ""))
                out.append(t)
        # ambiguous doc request (e.g. "what is it?") with no keyword but file hint may be weak
        if len(out) <= 5 and any(k in low for k in ("file", "read", "what is", "summar")):
            for t in [read_document, read_pdf, read_pdf_page]:
                if t.name not in seen:
                    seen.add(t.name)
                    out.append(t)
        # fallback: if heuristics added nothing beyond base and hint looks generic, keep base (saves tokens); full set only when hint empty
        return out if out else list(tools)

    bound_fixed = llm_instance.bind_tools(_filtered_tools(user_input))
    last_text: str = ""
    last_text_tier: Optional[str] = None
    last_results: List[str] = []
    last_llm: Any = llm_instance
    provider_error: Optional[Exception] = None
    rounds_used = 0
    round_tier: Optional[str] = None
    tokens = on_token if isinstance(on_token, TokenStream) else TokenStream(on_token, on_reset)
    live = tokens if tokens.streaming else None

    def _note_final_tier(name: Optional[str]) -> None:
        if final_tier is not None and name:
            final_tier[:] = [name]

    def _cancelled() -> bool:
        try:
            return bool(cancel is not None and cancel())
        except Exception:
            return False

    while rounds_used < max_rounds:
        budget.check_time()
        if _cancelled():
            raise TurnCancelled("client disconnected")
        try:
            budget.count_round()
        except BudgetExhausted:
            # Shared round budget spent (e.g. nested loops in Deep
            # Mode): stop chaining and synthesize from results so far,
            # exactly like reaching max_rounds.
            break
        tier_name: Optional[str] = None
        bound: Any = bound_fixed
        if llm_provider is not None:
            try:
                tier_name, round_llm = llm_provider()
            except TurnCancelled:
                raise
            except Exception as e:
                # No live tier left: finish from partial results below
                # (or raise when nothing was produced at all).
                provider_error = e
                break
            try:
                bound = round_llm.bind_tools(_filtered_tools(user_input))
            except BudgetExhausted:
                raise
            except TurnCancelled:
                raise
            except Exception as e:
                _note_tier_failure(tier_name, e)
                continue
            last_llm = round_llm
        try:
            if live is not None:
                live.reset_for_new_call()
            response = agent._invoke_bounded(bound, messages, budget=budget, on_token=live, tier_name=tier_name)
        except BudgetExhausted:
            raise
        except TurnCancelled:
            raise
        except Exception as e:
            if tier_name is None:
                raise
            # Same round retries instantly on the next live tier;
            # collected tool results are kept, not discarded.
            _note_tier_failure(tier_name, e)
            continue
        rounds_used += 1
        round_tier = tier_name
        if tier_name is not None:
            if tier_trace is not None and tier_name not in tier_trace:
                tier_trace.append(tier_name)
            try:
                _record_tier_success(tier_name)
            except Exception:
                pass
        text: str = _as_text(response.content).strip()
        if text:
            last_text = text
            last_text_tier = round_tier
        tool_calls: List[Any] = list(getattr(response, "tool_calls", None) or [])
        # Fallback: leaked JSON in content (free-tier tool-calling failure)
        if not tool_calls:
            try:
                fb = _fallback_tool_calls_from_text(text)
                if fb:
                    tool_calls = fb  # type: ignore[assignment]
                    # JSON was the tool call, not an answer to show
                    last_text = ""
            except Exception:
                pass
        if on_progress is not None and tool_calls:
            try:
                names: List[str] = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tc_name = tc.get("name", "")
                    else:
                        tc_name = getattr(tc, "name", "")
                    if tc_name and str(tc_name) not in names:
                        names.append(str(tc_name))
                if names:
                    on_progress("Using tools: " + ", ".join(names))
            except Exception:
                pass
        if not tool_calls:
            _note_final_tier(round_tier)
            return _with_sources(text if text else "I couldn't generate a response. Please try again.")
        try:
            # Parallel execution for read-only tools, serial for mutating
            execution_mode = "parallel" if _has_read_only_tools(tool_calls) else "serial"
            try:
                record_tool_execution_mode("batch", execution_mode)
            except Exception:
                pass
            last_results = _execute_tool_calls_parallel(tool_calls, budget)
            for tc, result_text in zip(tool_calls, last_results):
                if isinstance(tc, dict):
                    tc_name = tc.get("name", "")
                else:
                    tc_name = getattr(tc, "name", "")
                try:
                    with trace_tool_call(request_id or "toolloop", tc_name, execution_mode):
                        _record_tool(tc_name)
                        _record_search_sources(result_text, tc_name)
                except Exception:
                    _record_tool(tc_name)
                    _record_search_sources(result_text, tc_name)
        except BudgetExhausted:
            last_results.append(
                "[budget] Tool budget exhausted; no further tool calls. "
                "Synthesize from results so far."
            )
            break
        for result_text in last_results:
            _note_search(result_text)
        if budget.external_tokens > MAX_EXTERNAL_TOKENS:
            last_results.append(
                "[budget] External content budget exhausted; "
                "synthesize from results so far."
            )
            break
        messages.append(
            HumanMessage(
                content=(
                    "Tool results for your last action:\n"
                    + "\n".join(last_results)[:6000]
                    + "\nNow write your final answer to the user using these results. "
                    "Only call another tool if you still lack something essential."
                )
            )
        )
    if _cancelled():
        raise TurnCancelled("client disconnected")
    if rounds_used == 0 and not last_results:
        # Every tier failed before producing anything: honest error for
        # the outer cascade (which fails over or reports all-tiers-down).
        if provider_error is not None:
            raise provider_error
    # Budget exhausted: one final no-tools synthesis call. The last
    # working tier goes first; if it died mid-task, fail over through
    # the provider so collected tool results still become a full answer
    # on the next live tier instead of a salvaged partial. Salvage below
    # is the last resort, and budget exhaustion is never retried (it is
    # our limit, not the provider's).
    # ponytail: cap synthesis join (was unbounded) — prevents 8k overflow on GitHub lane
    _synthesis_blob = "\n".join(last_results)[:6000]
    _synth_system = ("Summarize the tool results below into a concise "
                     "final answer. Do not call any tools.")
    if is_strict_tier(round_tier):
        _synth_system += " " + STRICT_GROUNDING_PARAGRAPH
    synthesis_messages: List[BaseMessage] = [
        SystemMessage(content=_synth_system),
        HumanMessage(
            content="Results:\n"
            + _synthesis_blob
            + "\n\nOriginal request:\n"
            + user_input
        ),
    ]
    try:
        if live is not None:
            live.reset_for_new_call()
        final = agent._invoke_bounded(
            last_llm,
            synthesis_messages,
            timeout=SYNTHESIS_TIMEOUT_SECONDS,
            budget=budget,
            on_token=live,
            tier_name=round_tier,
        )
        text = _as_text(final.content).strip()
        if text:
            _note_final_tier(round_tier)
            return _with_sources(text)
    except BudgetExhausted:
        pass
    except TurnCancelled:
        raise
    except Exception as e:
        _note_tier_failure(round_tier, e)
        if llm_provider is not None:
            while True:
                try:
                    synthesis_tier, synthesis_llm = llm_provider()
                except TurnCancelled:
                    raise
                except Exception:
                    break
                try:
                    if live is not None:
                        live.reset_for_new_call()
                    final = agent._invoke_bounded(
                        synthesis_llm,
                        synthesis_messages,
                        timeout=SYNTHESIS_TIMEOUT_SECONDS,
                        budget=budget,
                        on_token=live,
                        tier_name=synthesis_tier,
                    )
                except BudgetExhausted:
                    break
                except Exception as e2:
                    _note_tier_failure(synthesis_tier, e2)
                    continue
                try:
                    _record_tier_success(synthesis_tier)
                except Exception:
                    pass
                text = _as_text(final.content).strip()
                if text:
                    _note_final_tier(synthesis_tier)
                    return _with_sources(text)
                break
    if last_text.strip():
        _note_final_tier(last_text_tier)
        return _with_sources(
            last_text.rstrip()
            + "\n\n[Note: I could only produce a partial answer — "
            "a model failed midway, so some steps may be missing.]"
        )
    if last_results:
        # Synthesis died on every tier (free-tier 429/down mid-turn) but a
        # tool already answered (e.g. Groq ran check_logic): show those
        # collected results instead of an error-only message. Capped so one
        # transcript cannot flood context; STATUS markers already tell the
        # model/user what succeeded.
        salvage = "\n".join(last_results).strip()[:4000]
        _note_final_tier(last_text_tier or round_tier)
        return _with_sources(
            "All models failed while composing the final summary, "
            "but here are the tool results that did come back:\n\n"
            + salvage
        )
    return _with_sources(
        "I gathered partial results but couldn't finish composing the answer. "
        "Please try again or simplify the request."
    )
