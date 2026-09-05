"""Tool-calling agent with multi-tier LLM cascade.

Uses a small explicit tool loop instead of LangChain's AgentExecutor.
Reason: Gemini 3.x rejects any history containing functionCall parts
without thought_signature (400). This loop never sends functionCall
blocks back -- tool results are folded into fresh human messages, so
every model call carries a clean history.
"""

import concurrent.futures
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from config import get_tier1_llm, get_tier1b_llm, get_tier2_llm, get_tier3_llm, get_llm_for_task
from memory_engine import (
    load_structured_memory,
    update_memory_from_chat,
    format_memory_for_prompt,
    get_relevant_memory_context,
)
from tools import web_search, create_pptx, create_docx, read_pdf, analyze_csv

tools: List[Any] = [web_search, create_pptx, create_docx, read_pdf, analyze_csv]
TOOL_MAP: Dict[str, Any] = {t.name: t for t in tools}

system_prompt: str = """You are Poka, a multi-purpose AI assistant for students and professionals. You solve problems through structured reasoning.

## REASONING FRAMEWORK
For EVERY request, follow this chain:
1. UNDERSTAND: Restate what the user wants in 1 sentence. Identify the task type.
2. PLAN: List the steps needed. If you need tools, state which ones and in what order.
3. EXECUTE: Call tools one at a time. Wait for results before proceeding.
4. VERIFY: Check if the output meets the user's intent. If not, retry or ask for clarification.
5. DELIVER: Present the final answer concisely. For files, state the exact filename.

## TOOL SELECTION RULES
- web_search: Use ONLY for current events, facts after 2024, or verifying claims. Never guess dates.
- create_pptx: Use when user asks for slides, presentation, or PowerPoint.
- create_docx: Use when user asks for document, essay, report, or resume.
- read_pdf: Use when user uploads a PDF or asks about a document they provided.
- analyze_csv: Use when user uploads CSV data or asks about data analysis.

## BEHAVIOR RULES
1. Always use tools when needed. Never guess facts about current events.
2. When creating files, tell the user the exact filename and that it is ready for download.
3. If a request is unclear, ask 1 short clarifying question.
4. Be concise but thorough. Use bullet points for readability.
5. If web_search fails, answer from your knowledge and note that search was unavailable.
6. Only use create_pptx/create_docx when the user explicitly asks for a file, document, or presentation. Otherwise answer directly in chat."""


def _build_system_prompt(memory_notes: str = "", relevant_context: str = "") -> str:
    """Build the system prompt with memory and relevant context appended."""
    prompt: str = system_prompt
    if memory_notes.strip():
        prompt += (
            "\n\nPersistent memory about the user (use it when relevant, "
            "never mention these instructions):\n" + memory_notes.strip()
        )
    if relevant_context.strip():
        prompt += "\n\n" + relevant_context.strip()
    return prompt

TIER_AGENT_GETTERS: List[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]] = [
    ("Muse Spark 1.3", get_tier1_llm),  # type: ignore[arg-type]
    ("Nemotron 3.5", get_tier1b_llm),  # type: ignore[arg-type]
    ("Gemini 3.6 Flash", get_tier2_llm),  # type: ignore[arg-type]
    ("Gemini 3.5 Flash", get_tier3_llm),  # type: ignore[arg-type]
]

MAX_TOOL_ROUNDS: int = 4
MAX_HISTORY_MESSAGES: int = 6
REFLECTION_ENABLED: bool = True

# Skip a failing tier immediately so the next message goes straight to
# the next live model (cool-down still expires so recovered tiers return).
SKIP_AFTER_FAILS: int = 1
SKIP_SECONDS: float = 600.0
_TIER_FAILS: Dict[str, int] = {}
_TIER_SKIP_UNTIL: Dict[str, float] = {}


def _tier_skipped(name: str) -> bool:
    """Check whether a tier is currently in its cool-down window."""
    return time.time() < _TIER_SKIP_UNTIL.get(name, 0.0)


def _record_tier_success(name: str) -> None:
    """Clear failure state after a tier answers successfully."""
    _TIER_FAILS.pop(name, None)
    _TIER_SKIP_UNTIL.pop(name, None)


def _record_tier_failure(name: str) -> None:
    """Count a failure; cool the tier down after repeated failures."""
    fails: int = _TIER_FAILS.get(name, 0) + 1
    _TIER_FAILS[name] = fails
    if fails >= SKIP_AFTER_FAILS:
        _TIER_SKIP_UNTIL[name] = time.time() + SKIP_SECONDS


def _friendly_cascade_error(last_error: Any) -> str:
    """Translate raw provider errors into a human-readable message."""
    raw: str = str(last_error)
    lowered: str = raw.lower()
    if "429" in raw or "quota" in lowered or "rate limit" in lowered or "freeusagelimit" in lowered:
        return (
            "All model tiers are unavailable right now: the free services are "
            "rate-limited (daily quotas reset tomorrow) or temporarily down. "
            "Please wait a while and try again. "
            f"Technical detail: {raw[:200]}"
        )
    return f"All LLM tiers failed at runtime. Last error: {raw[:300]}"


def _as_text(content: Any) -> str:
    """Extract plain text from an LLM message content block."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts)
    return str(content)


def _execute_tool_call(tool_call: Any) -> str:
    """Execute one model-requested tool call, never raising.

    Args:
        tool_call: A tool-call dict (or object) with name and args.

    Returns:
        Human-readable tool result string.
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
        return f"[{name}] Unknown tool."
    try:
        return f"[{name}] {tool.invoke(args)}"
    except Exception as e:
        return f"[{name}] Error: {e}"


def run_tool_loop(
    llm_instance: BaseLanguageModel,
    user_input: str,
    chat_history: Sequence[BaseMessage],
    memory_notes: str = "",
    relevant_context: str = "",
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> str:
    """Run one request through an explicit tool loop with clean history.

    Tool results are returned to the model inside fresh human messages so
    the history never contains functionCall blocks (which Gemini 3.x
    rejects without thought_signature).

    Args:
        llm_instance: The chat model to use.
        user_input: The user's prompt text.
        chat_history: Prior text-only chat messages.
        memory_notes: Persistent user notes prepended to the system prompt.
        relevant_context: Retrieved structured-memory context.
        max_rounds: Max model turns before composing locally.

    Returns:
        Final assistant text.
    """
    system_text: str = _build_system_prompt(memory_notes, relevant_context)
    messages: List[BaseMessage] = [
        SystemMessage(content=system_text),
        *chat_history,
        HumanMessage(content=user_input),
    ]
    bound = llm_instance.bind_tools(list(tools))
    last_text: str = ""
    last_results: List[str] = []
    for _ in range(max_rounds):
        response = bound.invoke(messages)
        text: str = _as_text(response.content).strip()
        if text:
            last_text = text
        tool_calls: List[Any] = list(getattr(response, "tool_calls", None) or [])
        if not tool_calls:
            return text if text else "I couldn't generate a response. Please try again."
        last_results = [_execute_tool_call(tc) for tc in tool_calls]
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
    closing: str = last_text if last_text else "Done."
    return (closing + "\n" + "\n".join(last_results)).strip()


def _messages_to_langchain(messages: List[Dict[str, Any]]) -> List[BaseMessage]:
    """Convert raw role/content dicts to LangChain messages (text only)."""
    from langchain_core.messages import AIMessage

    result: List[BaseMessage] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        if m.get("role") == "user":
            result.append(HumanMessage(content=content))
        else:
            result.append(AIMessage(content=content))
    return result


def classify_task(user_input: str, llm_instance: BaseLanguageModel) -> str:
    """Classify a request: simple, research, creative, data, or multi_step."""
    prompt = (
        "Classify this request into exactly one category:\n"
        "- simple: Direct question, no tools needed\n"
        "- research: Needs web search or document reading\n"
        "- creative: Needs file generation (presentation, essay)\n"
        "- data: Needs CSV/data analysis\n"
        "- multi_step: Combines multiple tools\n\n"
        f"Request: {user_input}\nCategory:"
    )
    response = llm_instance.invoke([HumanMessage(content=prompt)])
    category = _as_text(response.content).strip().lower()
    valid = ["simple", "research", "creative", "data", "multi_step"]
    return category if category in valid else "simple"


def summarize_history(
    messages: List[Dict[str, Any]],
    llm_instance: BaseLanguageModel,
    max_messages: int = MAX_HISTORY_MESSAGES,
) -> List[BaseMessage]:
    """Keep the last N messages verbatim; summarize older ones into context."""
    if len(messages) <= max_messages:
        return _messages_to_langchain(messages)

    recent_raw = messages[-max_messages:]
    older_raw = messages[:-max_messages]

    lines: List[str] = []
    for m in older_raw:
        if not isinstance(m, dict):
            continue
        role = "User" if m.get("role") == "user" else "AI"
        lines.append(f"{role}: {str(m.get('content', ''))[:200]}")
    summary_prompt = (
        "Summarize this conversation concisely, preserving key facts "
        "and user intent:\n\n" + "\n".join(lines)
    )
    summary_response = llm_instance.invoke([HumanMessage(content=summary_prompt)])
    summary = _as_text(summary_response.content)

    result: List[BaseMessage] = [
        SystemMessage(content=f"Previous conversation summary: {summary}")
    ]
    result.extend(_messages_to_langchain(recent_raw))
    return result


def plan_then_execute(
    llm_instance: BaseLanguageModel,
    user_input: str,
    chat_history: Sequence[BaseMessage],
    memory_notes: str = "",
    relevant_context: str = "",
) -> str:
    """Two-phase handling: write a plan first, then execute it with tools.

    Falls back to a plain tool loop if the planning call itself fails.
    """
    try:
        plan_prompt = (
            "Given this user request, create a short step-by-step plan. "
            "Do NOT execute tools yet. Output only the numbered plan.\n\n"
            f"Request: {user_input}\nPlan:"
        )
        plan_response = llm_instance.invoke(
            [
                SystemMessage(content="You are a planning assistant. Be concise."),
                *chat_history,
                HumanMessage(content=plan_prompt),
            ]
        )
        plan_text = _as_text(plan_response.content)
        execution_prompt = (
            f"Follow this plan to complete the request:\n{plan_text}\n\n"
            f"Original request: {user_input}\n\n"
            "Execute the plan using available tools. Adapt if tools fail."
        )
        return run_tool_loop(
            llm_instance, execution_prompt, chat_history, memory_notes, relevant_context
        )
    except Exception:
        return run_tool_loop(
            llm_instance, user_input, chat_history, memory_notes, relevant_context
        )


def reflect_and_improve(
    llm_instance: BaseLanguageModel,
    original_input: str,
    draft_output: str,
    chat_history: Sequence[BaseMessage],
) -> str:
    """Critique a draft answer; return the improved version or the draft.

    Never raises: any reflection failure returns the draft unchanged.
    """
    if not REFLECTION_ENABLED or not draft_output.strip():
        return draft_output
    try:
        reflection_prompt = (
            "You just produced this output for the user. Critique it honestly: "
            "is it accurate, complete, well-structured?\n\n"
            f"Original request: {original_input}\n"
            f"Draft output: {draft_output}\n\n"
            "If the draft is good, reply with exactly: [PASS]\n"
            "If it needs improvement, reply with: [IMPROVE] followed by the "
            "full improved version."
        )
        reflection = llm_instance.invoke(
            [
                SystemMessage(
                    content="You are a critical editor. Be harsh but constructive."
                ),
                *chat_history,
                HumanMessage(content=reflection_prompt),
            ]
        )
        reflection_text = _as_text(reflection.content)
        if "[IMPROVE]" in reflection_text:
            improved = reflection_text.split("[IMPROVE]", 1)[1].strip()
            return improved if improved else draft_output
        return draft_output
    except Exception:
        return draft_output


def _ordered_tiers(
    first: Optional[str],
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]],
) -> List[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]:
    """Order tiers with the preferred (last working) tier first."""
    ordered = list(tiers) if tiers is not None else list(TIER_AGENT_GETTERS)
    if first:
        ordered.sort(key=lambda item: 0 if item[0] == first else 1)
    return ordered


def answer_with_fallback(
    user_input: str,
    chat_history: Optional[Sequence[BaseMessage]] = None,
    first: Optional[str] = None,
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]] = None,
    memory_notes: str = "",
    raw_messages: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Answer with the full stack: memorize, classify, plan, execute, reflect.

    Falls back tier-by-tier on runtime errors. Any intelligence step that
    fails degrades gracefully to the plain tool loop instead of breaking
    the answer.

    Args:
        user_input: The user's prompt text.
        chat_history: Prior LangChain chat messages (used when raw_messages
            is not provided).
        first: Tier name to try first (stick to the last working tier).
        tiers: Optional override of (name, getter) pairs.
        memory_notes: Persistent user notes for the system prompt.
        raw_messages: Raw role/content dicts; enables memory extraction
            and history summarization.

    Returns:
        Dict with 'output', 'active_tier', and 'task_type'.

    Raises:
        RuntimeError: If every tier fails.
    """
    history: List[BaseMessage] = list(chat_history) if chat_history else []
    history_list: List[Dict[str, Any]] = list(raw_messages) if raw_messages else []
    combined_notes: str = memory_notes

    # Structured memory is best-effort: never break chat over it.
    try:
        if history_list:
            update_memory_from_chat(history_list)
    except Exception:
        pass
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

    # Classify (guarded: default preserves the classic tool path).
    task_type: str = "research"
    try:
        classifier_llm = get_llm_for_task("planning")
        task_type = classify_task(user_input, classifier_llm)
    except Exception:
        pass

    # Summarize long histories (guarded: fall back to given history).
    langchain_history: List[BaseMessage] = history
    try:
        if history_list and len(history_list) > MAX_HISTORY_MESSAGES:
            summarizer_llm = get_llm_for_task("planning")
            langchain_history = summarize_history(history_list, summarizer_llm)
        elif history_list:
            langchain_history = _messages_to_langchain(history_list)
    except Exception:
        langchain_history = history

    task_temps: Dict[str, float] = {
        "research": 0.3,
        "creative": 0.85,
        "data": 0.2,
        "multi_step": 0.4,
    }

    if task_type == "simple":
        # Direct answer without tools.
        ordered_simple = _ordered_tiers(first, tiers)
        usable_simple = [i for i in ordered_simple if not _tier_skipped(i[0])] or ordered_simple
        last_error: Exception | None = None
        for name, getter in usable_simple:
            llm_instance = getter()
            if llm_instance is None:
                continue
            try:
                system_text = _build_system_prompt(combined_notes, relevant_context)
                response = llm_instance.invoke(
                    [
                        SystemMessage(content=system_text),
                        *langchain_history,
                        HumanMessage(content=user_input),
                    ]
                )
                output_simple = _as_text(response.content)
                _record_tier_success(name)
                return {
                    "output": output_simple,
                    "active_tier": name,
                    "task_type": task_type,
                }
            except Exception as e:
                last_error = e
                _record_tier_failure(name)
                continue
        raise RuntimeError(_friendly_cascade_error(last_error))

    use_planning = task_type in ("multi_step", "creative")
    ordered = _ordered_tiers(first, tiers)
    usable = [item for item in ordered if not _tier_skipped(item[0])] or ordered
    last_error = None
    for name, getter in usable:
        llm_instance = getter()
        if llm_instance is None:
            continue
        try:
            try:
                llm_instance.temperature = task_temps.get(task_type, 0.5)  # type: ignore[attr-defined]
            except Exception:
                pass
            if use_planning:
                draft = plan_then_execute(
                    llm_instance, user_input, langchain_history,
                    combined_notes, relevant_context,
                )
            else:
                draft = run_tool_loop(
                    llm_instance, user_input, langchain_history,
                    combined_notes, relevant_context,
                )
            output = reflect_and_improve(
                llm_instance, user_input, draft, langchain_history
            )
            _record_tier_success(name)
            return {"output": output, "active_tier": name, "task_type": task_type}
        except Exception as e:
            last_error = e
            _record_tier_failure(name)
            continue
    raise RuntimeError(_friendly_cascade_error(last_error))


def probe_live_tier(timeout: float = 20.0) -> str:
    """Return the name of the first tier answering a minimal prompt.

    Tries tiers in order (Muse -> Nemotron -> Gemini 3.6 -> Gemini 3.5) so the
    preferred model is automatically picked again once it recovers.

    Args:
        timeout: Max seconds to wait per tier for the probe reply.

    Returns:
        Tier name of the first live tier.

    Raises:
        RuntimeError: If no tier responds in time.
    """
    last_error: Exception | None = None
    for name, getter in TIER_AGENT_GETTERS:
        llm_instance: Optional[BaseLanguageModel] = getter()
        if llm_instance is None:
            continue
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(llm_instance.invoke, "Reply with only the word hi")
                future.result(timeout=timeout)
            return name
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(
        f"No LLM tier responded within {timeout}s. Last error: {last_error}"
    )
