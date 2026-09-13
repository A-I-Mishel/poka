"""Tool execution: single funnel plus the main tool loop.

Every model-requested tool call flows through _execute_tool_call, which
charges the request budget, bounds wall-clock time, re-binds the
submitting request's user (worker threads do not inherit contextvars),
and returns explicit STATUS markers so the model can distinguish success
from failure.

run_tool_loop keeps history clean for Gemini 3.x (no functionCall
blocks ever go back): tool results return inside fresh human messages.
"""

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from services.context import get_current_user_id, get_limit_key, set_limit_key, set_current_user_id
from services.context_budget import CTX_HISTORY_TOKENS, CTX_MEMORY_TOKENS, fit_history, fit_text
from services.limits import (
    MAX_EXTERNAL_TOKENS,
    MAX_QUERY_CHARS,
    MAX_TOOL_RESULT_TOKENS,
    MAX_TOOL_ROUNDS,
    TOOL_TIMEOUT_SECONDS,
)
from services.obs import timed as obs_timed
from services.storage import MAX_SOURCES, clean_source_record
from services.tokens import count_tokens, truncate_tokens
from tools import web_search, create_pptx, build_presentation, create_docx, build_document, create_pdf, create_markdown, create_doc, create_html, read_output, read_pdf, read_pdf_page, read_document, analyze_csv, csv_inspect, search_documents, search_gmail, read_gmail, create_gmail_draft, send_gmail, list_calendar_events, create_calendar_event, delete_calendar_event, list_tables, describe_table, query_database, import_csv_table, execute_sql, run_python, workspace_list, workspace_read, workspace_write, workspace_delete, run_code, list_mcp_tools, call_mcp_tool
from tools.search_tool import extract_cited_sources

from agent.budget import BudgetExhausted, RequestBudget
from agent.cascade import (
    _record_tier_failure,
    _record_tier_success,
    classify_provider_error,
)
from agent.executor import TokenStream, _call_bounded

import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.prompts import _as_text, _build_system_prompt, strip_internal_reasoning

tools: List[Any] = [web_search, search_documents, search_gmail, read_gmail, create_gmail_draft, send_gmail, list_calendar_events, create_calendar_event, delete_calendar_event, list_tables, describe_table, query_database, import_csv_table, execute_sql, run_python, workspace_list, workspace_read, workspace_write, workspace_delete, run_code, list_mcp_tools, call_mcp_tool, create_pptx, build_presentation, create_docx, build_document, create_pdf, create_markdown, create_doc, create_html, read_output, read_pdf, read_pdf_page, read_document, analyze_csv, csv_inspect]
TOOL_MAP: Dict[str, Any] = {t.name: t for t in tools}

MAX_TOOL_ROUNDS = MAX_TOOL_ROUNDS  # re-exported from services.limits

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
    """
    if budget is None:
        budget = RequestBudget()
    mem_fit = fit_text(
        (memory_notes.strip() + "\n" + relevant_context.strip()).strip(),
        CTX_MEMORY_TOKENS,
    )
    system_text: str = _build_system_prompt(mem_fit, "", project_context)
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

    bound_fixed = llm_instance.bind_tools(list(tools))
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

    while rounds_used < max_rounds:
        budget.check_time()
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
            except Exception as e:
                # No live tier left: finish from partial results below
                # (or raise when nothing was produced at all).
                provider_error = e
                break
            try:
                bound = round_llm.bind_tools(list(tools))
            except BudgetExhausted:
                raise
            except Exception as e:
                _note_tier_failure(tier_name, e)
                continue
            last_llm = round_llm
        try:
            if live is not None:
                live.reset_for_new_call()
            response = agent._invoke_bounded(bound, messages, budget=budget, on_token=live)
        except BudgetExhausted:
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
            last_results = []
            for tc in tool_calls:
                result_text = _execute_tool_call(tc, budget)
                last_results.append(result_text)
                if isinstance(tc, dict):
                    tc_name = tc.get("name", "")
                else:
                    tc_name = getattr(tc, "name", "")
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
                    + "\n".join(last_results)
                    + "\nNow write your final answer to the user using these results. "
                    "Only call another tool if you still lack something essential."
                )
            )
        )
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
    synthesis_messages: List[BaseMessage] = [
        SystemMessage(
            content="Summarize the tool results below into a concise "
            "final answer. Do not call any tools."
        ),
        HumanMessage(
            content="Results:\n"
            + "\n".join(last_results)
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
            timeout=60.0,
            budget=budget,
            on_token=live,
        )
        text = _as_text(final.content).strip()
        if text:
            _note_final_tier(round_tier)
            return _with_sources(text)
    except BudgetExhausted:
        pass
    except Exception as e:
        _note_tier_failure(round_tier, e)
        if llm_provider is not None:
            while True:
                try:
                    synthesis_tier, synthesis_llm = llm_provider()
                except Exception:
                    break
                try:
                    if live is not None:
                        live.reset_for_new_call()
                    final = agent._invoke_bounded(
                        synthesis_llm,
                        synthesis_messages,
                        timeout=60.0,
                        budget=budget,
                        on_token=live,
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
    return _with_sources(
        "I gathered partial results but couldn't finish composing the answer. "
        "Please try again or simplify the request."
    )
