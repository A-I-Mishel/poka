"""Agent runtime: request orchestration over the agent components.

One user message flows through memorize → classify → plan/execute →
reflect, with every step funneled through the cascade (agent.cascade),
budgets (agent.budget), and bounded invocation (agent.executor).

Public contract: answer_with_fallback() returns an AgentResult dict with
'output', 'active_tier', 'task_type', 'request_id'; probe_live_tier()
names the first responding tier.

Answer stages (history shaping, citation checks, reflection) live in
agent.answer; this module re-exports them so `agent.runtime.X` keeps
working.
"""

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from config import CHEAP_TIERS, SYNTHESIS_TIERS, TASK_TEMPERATURES, get_tier_llm
from services.context import get_current_user_id
from services.limits import MAX_DEEP_LLM_CALLS, MAX_DEEP_TOOL_CALLS, MAX_DEEP_TOOL_ROUNDS
from services.memory import (
    format_memory_for_prompt,
    get_relevant_memory_context,
    load_structured_memory,
    update_memory_incremental,
)
from services.obs import event as obs_event, trace_llm_call

from agent.answer import (
    AgentResult as AgentResult,
    MAX_HISTORY_MESSAGES,
    _SUMMARY_CACHE,
    _SUMMARY_CACHE_MAX,
    _clear_summary_cache as _clear_summary_cache,
    _history_key,
    _reflect_with_fallback,
    _unknown_cited_urls as _unknown_cited_urls,
    _verify_citations,
    summarize_history,
)
from agent.budget import BudgetExhausted, RequestBudget, TurnCancelled
from agent.cascade import ROUTER_STATS, _run_cascade_step, _usable_tiers
from agent.executor import TokenStream
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.planning import plan_then_execute
from agent.prompts import STRICT_GROUNDING_PARAGRAPH, _as_text, _build_system_prompt, _messages_to_langchain, is_strict_tier, strip_internal_reasoning
from agent.reflection import should_reflect
from agent.router import classify_task, get_route_corrections, rule_route, rule_route_conf
from agent.toolrun import MAX_TOOL_ROUNDS, run_tool_loop
from agent.vision import _try_vision_answer

logger = logging.getLogger(__name__)

# Short inputs without any attachment/tool hints are answered directly:
# with no evidence of tool need, an LLM classify call is pure waste.
SHORT_DIRECT_CHARS: int = 60
_HINT_MARKERS = ("[Attached", "[Content of", "upload ID", "read_document",
                 "read_pdf", "analyze_csv")


def answer_with_fallback(
    user_input: str,
    chat_history: Optional[Sequence[BaseMessage]] = None,
    first: Optional[str] = None,
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]] = None,
    memory_notes: str = "",
    raw_messages: Optional[List[Dict[str, Any]]] = None,
    deep_mode: bool = False,
    force_web_search: bool = False,
    image_upload_ids: Optional[List[str]] = None,
    project_context: str = "",
    on_token: Optional[Callable[[str], None]] = None,
    on_reset: Optional[Callable[[], None]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Answer with the full stack: memorize, classify, plan, execute, reflect.

    Falls back tier-by-tier on runtime errors. Any intelligence step that
    fails degrades gracefully instead of breaking the answer. Every model
    call is bounded in time and tagged with a request ID for diagnostics
    (tier/task logged; never prompts or keys).

    Args:
        user_input: The user's prompt text.
        chat_history: Prior LangChain chat messages (used when raw_messages
            is not provided).
        first: Tier name to try first (stick to the last working tier).
        tiers: Optional override of (name, getter) pairs.
        memory_notes: Persistent user notes for the system prompt.
        raw_messages: Raw role/content dicts of PRIOR messages only (the
            current input is passed separately and must appear exactly
            once); enables memory extraction and history summarization.
        deep_mode: When True, run planning + reflection (more calls).
        force_web_search: When True, execute a web search first (policy,
            not just a prompt hint).
    image_upload_ids: Upload IDs of attached images to analyze with a
    vision-capable tier when one is configured.
    project_context: Explicit user-controlled text for the current
    project, wrapped as untrusted data in the system prompt.
    Empty means Personal / no project context.
    on_token: Receives cumulative answer text live (real provider
    tokens, never replayed). on_reset fires before a new model call
    supersedes an earlier one in the same turn. Both default to None
    (historical silent behavior).
    on_progress: Receives one status line per tool round (tool names
    only) so stream consumers can show activity while answer tokens
    have not started flowing. Defaults to None (silent).
    cancel: Polled between tool rounds (and before final synthesis);
    True raises TurnCancelled, aborting without synthesis or
    persistence. Defaults to None (historical run-to-completion).

    Returns:
        Dict with 'output', 'active_tier', 'task_type', 'request_id',
        'tools_used' (names of tools executed by the successful attempt,
        possibly empty) and 'sources' (structured source records parsed
        from executed web-search output, possibly empty; vision
        fast-path reports neither).

    Raises:
        RuntimeError: If every tier fails (friendly message + ref ID).
    """
    request_id: str = uuid.uuid4().hex[:8]
    started_at: float = time.time()
    user_id = get_current_user_id()
    budget = RequestBudget()
    try:
        if cancel is not None and cancel():
            raise TurnCancelled("client disconnected")
    except TurnCancelled:
        raise
    except Exception:
        logger.debug("req=%s cancel pre-check failed; continuing", request_id, exc_info=True)
    if deep_mode:
        # Deep Mode chains tools until the model stops asking: raise
        # the round/LLM/tool caps together (the wall-clock deadline
        # and per-call timeouts still bound the request absolutely).
        budget.max_rounds = MAX_DEEP_TOOL_ROUNDS
        budget.max_llm = MAX_DEEP_LLM_CALLS
        budget.max_tools = MAX_DEEP_TOOL_CALLS
    # One shared stream per turn: every final-answer invoke below
    # reuses it, so resets coordinate across vision, cascade attempts,
    # tool rounds, and final synthesis.
    tokens = TokenStream(on_token, on_reset)
    live = tokens if tokens.streaming else None

    # Vision fast-path: attached images go to a vision-capable tier with
    # real image content (never a "you cannot view images" dead end when
    # such a tier is configured). Falls through to the normal cascade
    # otherwise — never claims analysis that did not happen.
    if image_upload_ids:
        vision_hit = _try_vision_answer(
            request_id, user_input, image_upload_ids, budget, first, tiers,
            live, on_reset,
        )
        if vision_hit is not None:
            return vision_hit
        # ponytail: vision requested but no vision tier answered — degraded
        # directly instead of burning a text-tier call that just says
        # "can't see". Upgrade to queued retry when Gemini quota recovers.
        try:
            from agent.cascade import _friendly_reason, last_tier_error
            hit = last_tier_error("Gemini 3.6 Flash") or last_tier_error("Gemini 3.5 Flash")
            if hit:
                why = _friendly_reason(hit[0])
            else:
                # ponytail: distinguish not-configured from rate-limited; full
                # error taxonomy when Gemini adds new vision models.
                from config import get_tier2_llm, get_tier3_llm
                if get_tier2_llm() is None and get_tier3_llm() is None:
                    why = "not configured (GEMINI_API_KEY missing on server)"
                else:
                    why = "unavailable"
        except Exception:
            why = "unavailable"
        return {
            "output": (
                "I couldn't view that image — no vision-capable model (Gemini) "
                f"answered ({why}). Check that the image is <5MB/<25MP and "
                "Gemini isn't rate-limited, then resend or pick Gemini 3.6 Flash explicitly."
            ),
            "active_tier": "vision-unavailable",
            "task_type": "vision",
            "request_id": request_id,
            "tools_used": [],
            "sources": [],
        }
    history: List[BaseMessage] = list(chat_history) if chat_history else []
    history_list: List[Dict[str, Any]] = list(raw_messages) if raw_messages else []
    combined_notes: str = memory_notes
    logger.info("req=%s start tiers=%s", request_id,
                [n for n, _ in _usable_tiers(
                    first, SYNTHESIS_TIERS if tiers is None else tiers)])
    obs_event("request.start", request_id=request_id)

    try:
        if history_list:
            update_memory_incremental(history_list)
    except Exception:
        logger.debug("req=%s memory update failed", request_id, exc_info=True)
    try:
        formatted_memory = format_memory_for_prompt(load_structured_memory())
    except Exception:
        formatted_memory = ""
    try:
        relevant_context = get_relevant_memory_context(user_input)
    except Exception:
        relevant_context = ""
    if formatted_memory:
        combined_notes = (combined_notes + "\n" + formatted_memory).strip()

    # Role tables (prod default only): cheap tiers for dumb calls,
    # synthesis tiers for final answers. Caller-supplied tables (tests,
    # explicit overrides) keep legacy behavior exactly.
    cheap_table = CHEAP_TIERS if tiers is None else tiers
    synth_table = SYNTHESIS_TIERS if tiers is None else tiers

    task_type: str = rule_route(user_input) or ""
    if task_type:
        ROUTER_STATS["rule"] += 1
    elif (len(user_input.strip()) <= SHORT_DIRECT_CHARS
            and not any(m in user_input for m in _HINT_MARKERS)):
        # Short input with no evidence of tool need: answering directly is
        # correct far more often than not, and an LLM classify call here
        # is pure quota burn. Attachment/tool hints bypass this (the gate
        # already proved tool relevance, e.g. teaching "Next" turns).
        ROUTER_STATS["rule"] += 1
        task_type = "simple"
    else:
        ROUTER_STATS["llm"] += 1
        try:
            _, task_type = _run_cascade_step(
                lambda _name, llm: classify_task(user_input, llm, budget, tier_name=_name),
                first, cheap_table,
            )
        except RuntimeError:
            # Classifier is down: never silently default tool-ish
            # requests to simple (no tools). Creation/doc signals fail
            # open to multi_step so the tool loop can still help.
            try:
                from services.normalize import any_hit as _any_hit
                from services.normalize import normalize_text as _norm

                _n = _norm(user_input)
                if _any_hit(_n, ("create", "presentation", "slides", "report",
                                 "document", "pdf", "docx", "csv", "code",
                                 "python", "script", "analyze", "search")):
                    task_type = "multi_step"
                else:
                    task_type = "simple"
            except Exception:
                task_type = "simple"
        except BudgetExhausted:
            # Budget exhausted during classification: propagate to stop
            # the request instead of falling back to a cheaper path.
            raise
        logger.info("req=%s task=%s", request_id, task_type)
    # Typo metadata for UX ("Did you mean...?") and ops. Never raises,
    # never alters routing — rule_route already ran above.
    try:
        _rt, _rconf = rule_route_conf(user_input)
        route_confidence: float = float(_rconf)
    except Exception:
        route_confidence = 0.0
    try:
        route_corrections: list = get_route_corrections(user_input)
    except Exception:
        route_corrections = []

    langchain_history: List[BaseMessage] = history
    try:
        if history_list and len(history_list) > MAX_HISTORY_MESSAGES:
            cache_key = _history_key(user_id, history_list)
            cached = _SUMMARY_CACHE.get(cache_key)
            if cached is not None:
                langchain_history = cached
            else:
                def _summarize(_name: str, llm: BaseLanguageModel) -> List[BaseMessage]:
                    return summarize_history(history_list, llm, budget=budget, tier_name=_name)

                with trace_llm_call(request_id, "summarize", "summarize") as _:
                    _, langchain_history = _run_cascade_step(_summarize, first, cheap_table)
                _SUMMARY_CACHE[cache_key] = langchain_history
                while len(_SUMMARY_CACHE) > _SUMMARY_CACHE_MAX:
                    _SUMMARY_CACHE.pop(next(iter(_SUMMARY_CACHE)))
        elif history_list:
            langchain_history = _messages_to_langchain(history_list)
    except RuntimeError:
        langchain_history = history
    except BudgetExhausted:
        raise

    def _is_managed_table(table: Any) -> bool:
        # Managed tables hold real shared getters, so per-task sizing via
        # get_tier_llm is thread-safe. Caller-supplied tables own their
        # instances and are used exactly as given (even on name collision).
        return table is None or table is SYNTHESIS_TIERS or table is CHEAP_TIERS

    def _size_llm_for_task(tier_name: str, llm: BaseLanguageModel) -> BaseLanguageModel:
        # Task temperature via a cached client for (tier, temperature):
        # cached instances are never mutated (thread-safe sharing). Only
        # for managed cascade tables -- a caller-supplied tiers table
        # owns its instances, so those are used exactly as given (with
        # the historical temperature hint) and never swapped for real
        # clients, even on a name collision.
        if _is_managed_table(tiers):
            try:
                sized = get_tier_llm(tier_name, temperature=TASK_TEMPERATURES.get(task_type, 0.5))
            except Exception:
                sized = None
            if sized is not None:
                return sized
            return llm
        try:
            llm.temperature = TASK_TEMPERATURES.get(task_type, 0.5)  # type: ignore[attr-defined]
        except Exception:
            logger.debug("req=%s task temperature hint failed", request_id, exc_info=True)
        return llm

    if task_type == "simple":
        def _answer_direct(_name: str, llm: BaseLanguageModel) -> str:
            llm = _size_llm_for_task(_name, llm)
            system_text = _build_system_prompt(
                combined_notes, relevant_context, project_context, simple=True)
            # Grounded for all tiers (weak tiers need it most, strong tiers
            # benefit too). is_strict_tier() still marks the weakest lanes.
            system_text += "\n\n" + STRICT_GROUNDING_PARAGRAPH
            with trace_llm_call(request_id, "simple", "simple") as _:
                response = agent._invoke_bounded(
                    llm,
                    [
                        SystemMessage(content=system_text),
                        *langchain_history,
                        HumanMessage(content=user_input),
                    ],
                    budget=budget,
                    on_token=live,
                    tier_name=_name,
                )
            return _as_text(response.content)

        # Synthesis table first; the full cascade is the escape hatch when
        # synthesis is down (answers then carry a degraded marker). Custom
        # tables run exactly once, as before.
        tables = [synth_table]
        if tiers is None:
            tables.append(None)
        degraded: Optional[Dict[str, str]] = None
        answer_attempts: List[str] = []
        while tables:
            table = tables.pop(0)
            try:
                active_tier, output_simple = _run_cascade_step(
                    _answer_direct, first, table, answer_attempts,
                    prefer_fast=True)
                break
            except BudgetExhausted as e:
                # Our limit, not the provider's: never retry, never fall back.
                raise RuntimeError(f"{e} (ref {request_id})") from e
            except RuntimeError as e:
                if table is SYNTHESIS_TIERS and tables:
                    degraded = {"requested": "synthesis",
                                "reason": "synthesis tiers unavailable"}
                    continue
                raise RuntimeError(f"{e} (ref {request_id})") from e
        else:  # pragma: no cover - loop always breaks or raises
            raise RuntimeError(f"All LLM tiers failed at runtime. (ref {request_id})")
        try:
            output_simple = strip_internal_reasoning(output_simple)
            # Weak-lane honesty: quality tiers down + weak tier answered
            # within synthesis -> mark degraded (UI can show honestly).
            if degraded is None:
                try:
                    from config import WEAK_FINAL_TIERS

                    if active_tier in WEAK_FINAL_TIERS:
                        degraded = {"requested": "quality",
                                    "reason": "quality tiers unavailable"}
                except Exception:
                    logger.debug("weak-tier marker failed", exc_info=True)
            latency_ms = int((time.time() - started_at) * 1000)
            logger.info(
                "req=%s user=%s task=%s tier=%s ok llm=%d tools=%d fallbacks=%d latency_ms=%d",
                request_id, user_id, task_type, active_tier,
                budget.llm_calls, budget.tool_calls,
                max(0, len(answer_attempts) - 1), latency_ms,
            )
            obs_event(
                "request.end", status="ok", request_id=request_id,
                duration_ms=float(latency_ms), tier=active_tier,
                task=task_type, llm_calls=budget.llm_calls,
                tool_calls=budget.tool_calls,
            )
            return {
                "output": output_simple,
                "active_tier": active_tier,
                "task_type": task_type,
                "request_id": request_id,
                "tools_used": [],
                "sources": [],
                "fallback": degraded,
                "route_confidence": route_confidence,
                "corrections": route_corrections,
            }
        except (RuntimeError, BudgetExhausted) as e:
            logger.warning("req=%s failed: %s", request_id, e)
            obs_event("request.end", status="error", request_id=request_id, errkind=type(e).__name__)
            raise RuntimeError(f"{e} (ref {request_id})") from e

    use_planning = deep_mode and task_type in ("multi_step", "creative")

    # Tool names and source records executed by the SUCCESSFUL tier
    # attempt only. Failed attempts re-raise for fallback, discarding
    # their partial entries so recorded provenance always belongs to
    # the final response.
    used_tools: List[str] = []
    used_sources: List[Dict[str, str]] = []

    def _make_tier_provider(pinned: Optional[Tuple[str, BaseLanguageModel]] = None,
                            failed: Optional[set] = None):
        """Stateful per-attempt failover across usable tiers.

        The pinned (name, model) pair — this cascade attempt's tier, if
        any — is served first, unless it is already in `failed` (e.g. a
        planning call just proved it dead: execution then continues
        directly on the next live tier with zero wasted retries);
        afterwards tiers come from cascade order minus failed and
        cooled-down ones. Getter failures cool their tier and move on.
        Healthy tiers are reusable across rounds (multi-round loops must
        not starve on a short tier table); only failed tiers are
        remembered and skipped. A caller-supplied `failed` set is shared
        (planning failures recorded there are honored here). Exhaustion
        raises a friendly error.
        """
        from agent.cascade import (
            _all_skipped_permanent,
            _friendly_cascade_error,
            _ordered_tiers,
            _record_tier_failure,
            classify_provider_error,
            last_tier_error,
        )

        if failed is None:
            failed = set()
        yielded_pinned = False
        last_error: Optional[Exception] = None

        def _provider() -> Tuple[str, BaseLanguageModel]:
            nonlocal yielded_pinned, last_error
            if (pinned is not None and not yielded_pinned
                    and pinned[0] not in failed):
                yielded_pinned = True
                return pinned[0], _size_llm_for_task(pinned[0], pinned[1])
            yielded_pinned = True
            # Fail fast when every tier is cooled for quota/auth/invalid:
            # retrying the whole dead table each round burns quota and
            # latency for zero chance of success.
            full_table = _ordered_tiers(first, synth_table)
            if full_table and _all_skipped_permanent(full_table):
                kind, detail = last_tier_error(full_table[0][0]) or ("rate_limit", "")
                raise RuntimeError(_friendly_cascade_error(f"{kind}: {detail}"))
            ordered = [
                item for item in _usable_tiers(first, synth_table, prefer_fast=True)
                if item[0] not in failed
            ]
            if not ordered:
                if last_error is not None:
                    raise RuntimeError(_friendly_cascade_error(last_error))
                raise RuntimeError("All LLM tiers failed at runtime.")
            for name, getter in ordered:
                try:
                    llm_instance = getter()
                except Exception as e:
                    last_error = e
                    failed.add(name)
                    try:
                        _record_tier_failure(name, classify_provider_error(e)[0], e)
                    except Exception:
                        logger.debug("req=%s tier failure record failed", request_id, exc_info=True)
                    continue
                if llm_instance is None:
                    failed.add(name)
                    continue
                return name, _size_llm_for_task(name, llm_instance)
            raise RuntimeError(_friendly_cascade_error(last_error))

        return _provider

    tooled_tiers: List[str] = []
    final_tier_box: List[str] = []

    def _answer_tooled(tier_name: str, llm: BaseLanguageModel) -> str:
        # Shared with the planning stage: a tier that dies on the
        # planning call is recorded here so the execution provider skips
        # it immediately (true continuation, no wasted retry on dead).
        prefailed: set = set()
        provider = _make_tier_provider(pinned=(tier_name, llm), failed=prefailed)
        mark = len(used_tools)
        mark_sources = len(used_sources)
        final_tier_box[:] = []
        final_tier: List[str] = final_tier_box
        try:
            if use_planning:
                draft = plan_then_execute(
                    llm, user_input, langchain_history, combined_notes,
                    relevant_context, budget, used_tools, used_sources,
                    project_context, provider, tooled_tiers, live, on_reset,
                    final_tier, MAX_DEEP_TOOL_ROUNDS, on_progress,
                    tier_name, prefailed, request_id,
                    cheap_tiers=(CHEAP_TIERS if tiers is None else None),
                    cancel=cancel,
                    strict=is_strict_tier(tier_name),
                )
            else:
                draft = run_tool_loop(
                    llm, user_input, langchain_history, combined_notes,
                    relevant_context, force_web_search,
                    MAX_DEEP_TOOL_ROUNDS if deep_mode else MAX_TOOL_ROUNDS,
                    budget, used_tools, used_sources,
                    project_context, provider, tooled_tiers, live, on_reset,
                    final_tier, on_progress, request_id, cancel,
                    strict=is_strict_tier(tier_name),
                )
            if should_reflect(task_type, draft, user_input, deep_mode):
                try:
                    if cancel is not None and cancel():
                        raise TurnCancelled("client disconnected")
                except TurnCancelled:
                    raise
                except Exception:
                    logger.debug("req=%s reflection cancel check failed", request_id, exc_info=True)
                improved, writer = _reflect_with_fallback(
                    llm, user_input, draft, langchain_history, budget,
                    task_type, tier_name,
                    cheap_tiers=(CHEAP_TIERS if tiers is None else None))
                if improved != draft:
                    # The visible answer is the rewrite, produced on this
                    # attempt's tier — not whichever tier ran the draft.
                    draft = improved
                    final_tier[:] = [writer or tier_name]
            elif not final_tier:
                final_tier[:] = [tier_name]
            if task_type == "research":
                # Grounded-link check: one cheap call only when the answer
                # links pages absent from retrieved sources.
                draft = _verify_citations(
                    draft, used_sources, budget,
                    cheap_tiers=(CHEAP_TIERS if tiers is None else None))
            return draft
        except Exception:
            del used_tools[mark:]
            del used_sources[mark_sources:]
            raise

    degraded_tooled: Optional[Dict[str, str]] = None
    try:
        answer_attempts = []
        _tooled_tables = [synth_table]
        if tiers is None:
            _tooled_tables.append(None)
        while _tooled_tables:
            _table = _tooled_tables.pop(0)
            try:
                active_tier, output = _run_cascade_step(
                    _answer_tooled, first, _table, answer_attempts,
                    prefer_fast=True)
                break
            except BudgetExhausted as e:
                raise RuntimeError(f"{e} (ref {request_id})") from e
            except RuntimeError as e:
                if _table is SYNTHESIS_TIERS and _tooled_tables:
                    degraded_tooled = {"requested": "synthesis",
                                       "reason": "synthesis tiers unavailable"}
                    continue
                raise RuntimeError(f"{e} (ref {request_id})") from e
        else:  # pragma: no cover - loop always breaks or raises
            raise RuntimeError(f"All LLM tiers failed at runtime. (ref {request_id})")
        # Attribute the tier that produced the visible answer: the final
        # call's tier when tracked, else the last involved tier. The old
        # tooled_tiers[-1] could name a tier whose text was superseded
        # (failover A->B->A reported B; reflection rewrites report the
        # rewriter, not the draft's tier).
        if final_tier_box:
            active_tier = final_tier_box[0]
        elif tooled_tiers:
            active_tier = tooled_tiers[-1]
        output = strip_internal_reasoning(output)
        if degraded_tooled is None:
            try:
                from config import WEAK_FINAL_TIERS

                if active_tier in WEAK_FINAL_TIERS:
                    degraded_tooled = {"requested": "quality",
                                       "reason": "quality tiers unavailable"}
            except Exception:
                logger.debug("weak-tier tooled marker failed", exc_info=True)
        latency_ms = int((time.time() - started_at) * 1000)
        logger.info(
            "req=%s user=%s task=%s tier=%s ok llm=%d tools=%d search=%d "
            "reflect=%d plan=%d ext=%d timeouts=%d fallbacks=%d latency_ms=%d",
            request_id, user_id, task_type, active_tier, budget.llm_calls,
            budget.tool_calls, budget.search_calls, budget.reflect_calls,
            budget.plan_calls, budget.external_tokens, budget.timeouts,
            max(0, len(answer_attempts) - 1), latency_ms,
        )
        obs_event(
            "request.end", status="ok", request_id=request_id,
            duration_ms=float(latency_ms), tier=active_tier,
            task=task_type, llm_calls=budget.llm_calls,
            tool_calls=budget.tool_calls, timeouts=budget.timeouts,
        )
        return {
            "output": output,
            "active_tier": active_tier,
            "task_type": task_type,
            "request_id": request_id,
            "tools_used": list(used_tools),
            "sources": [dict(s) for s in used_sources],
            "fallback": degraded_tooled,
            "route_confidence": route_confidence,
            "corrections": route_corrections,
        }
    except (RuntimeError, BudgetExhausted) as e:
        logger.warning("req=%s failed: %s", request_id, e)
        obs_event("request.end", status="error", request_id=request_id, errkind=type(e).__name__)
        raise RuntimeError(f"{e} (ref {request_id})") from e


def probe_live_tier(timeout: float = 20.0) -> str:
    """Return the name of the first tier answering a minimal prompt.

    Uses the same cascade policy (and bounded calls) as everything else.
    Prefer lazy first-request fallback over probing at startup.
    """
    try:
        name, _ = _run_cascade_step(
            lambda _n, llm: agent._invoke_bounded(llm, "Reply with only the word hi", timeout=timeout),
            None,
            None,
        )
        return name
    except RuntimeError as e:
        raise RuntimeError(f"No LLM tier responded within {timeout}s. Last error: {e}") from e
