"""Tool-calling agent with 3-tier LLM cascade.

Uses a small explicit tool loop instead of LangChain's AgentExecutor.
Reason: Gemini 3.x rejects any history containing functionCall parts
without thought_signature (400). This loop never sends functionCall
blocks back -- tool results are folded into fresh human messages, so
every model call carries a clean history.
"""

import concurrent.futures
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from config import get_tier1_llm, get_tier2_llm, get_tier3_llm
from tools import web_search, create_pptx, create_docx, read_pdf, analyze_csv

tools: List[Any] = [web_search, create_pptx, create_docx, read_pdf, analyze_csv]
TOOL_MAP: Dict[str, Any] = {t.name: t for t in tools}

system_prompt: str = """You are Poka, a multi-purpose AI assistant for students and professionals.

Your capabilities:
- web_search: Search the internet for current information
- create_pptx: Create a PowerPoint presentation (args: topic, content)
- create_docx: Create a Word document (args: title, content)
- read_pdf: Extract and summarize text from a PDF file (arg: file_path)
- analyze_csv: Analyze a CSV file and return statistics (arg: file_path)

Rules:
1. Always use tools when needed. Never guess facts about current events.
2. When creating files, tell the user the exact filename and that it is ready for download.
3. If a request is unclear, ask 1 short clarifying question.
4. Be concise but thorough. Use bullet points for readability.
5. If web_search fails, answer from your knowledge and note that search was unavailable.
6. Only use create_pptx/create_docx when the user explicitly asks for a file, document, or presentation. Otherwise answer directly in chat."""

TIER_AGENT_GETTERS: List[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]] = [
    ("Muse Spark 1.3", get_tier1_llm),  # type: ignore[arg-type]
    ("Gemini 3.6 Flash", get_tier2_llm),  # type: ignore[arg-type]
    ("Gemini 3.5 Flash", get_tier3_llm),  # type: ignore[arg-type]
]

MAX_TOOL_ROUNDS: int = 4


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
        max_rounds: Max model turns before composing locally.

    Returns:
        Final assistant text.
    """
    messages: List[BaseMessage] = [
        SystemMessage(content=system_prompt),
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
) -> Dict[str, Any]:
    """Answer a request, cascading tiers on runtime errors.

    Args:
        user_input: The user's prompt text.
        chat_history: Prior text-only chat messages.
        first: Tier name to try first (stick to the last working tier).
        tiers: Optional override of (name, getter) pairs.

    Returns:
        Dict with 'output' text and 'active_tier' name.

    Raises:
        RuntimeError: If every tier fails.
    """
    history: List[BaseMessage] = list(chat_history) if chat_history else []
    last_error: Exception | None = None
    for name, getter in _ordered_tiers(first, tiers):
        llm_instance: Optional[BaseLanguageModel] = getter()
        if llm_instance is None:
            continue
        try:
            output: str = run_tool_loop(llm_instance, user_input, history)
            return {"output": output, "active_tier": name}
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(
        f"All LLM tiers failed at runtime. Last error: {last_error}"
    )


def probe_live_tier(timeout: float = 20.0) -> str:
    """Return the name of the first tier answering a minimal prompt.

    Tries tiers in order (Muse -> Gemini 3.6 -> Gemini 3.5) so Muse is
    automatically preferred again once its endpoint recovers.

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
