"""Bounded invocation: every model/tool call runs under a deadline.

Design (see agent docstring for the cancellation model):
- Provider-native HTTP timeouts (config.py request_timeout) truly abort
  hung calls; this layer guarantees the caller regains control.
- ONE shared daemon-thread pool (_bounded_pool) backs all bounded calls:
  at most _BOUNDED_MAX_WORKERS threads ever exist, they never block
  process exit, and a caller timeout orphans only the result, never a
  thread. Never submit _call_bounded from inside a pool worker.
- Every model invocation also charges the request budget first.
- Model calls stream with a first-token deadline
  (services.limits.FIRST_TOKEN_TIMEOUT_SECONDS): a tier that stays
  silent past the deadline raises TimeoutError so the cascade fails
  over to the next tier immediately. The remaining tokens then use the
  regular total timeout. Models without .stream() (legacy/test
  doubles) use plain .invoke() with the total timeout only.
- Live tokens: callers may pass on_token to receive cumulative answer
  text as it arrives (real provider tokens, never replayed). Use
  TokenStream to forward them and reset the consumer whenever a new
  call supersedes an earlier one in the same turn.
"""

import concurrent.futures
import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Iterator, List, Optional

from langchain_core.language_models.base import BaseLanguageModel

from agent.prompts import _as_text, sanitize_messages_for_provider
from services.limits import FIRST_TOKEN_TIMEOUT_OLLAMA_SECONDS, FIRST_TOKEN_TIMEOUT_OPENROUTER_SECONDS, FIRST_TOKEN_TIMEOUT_SECONDS, MODEL_TIMEOUT_SECONDS
from services.obs import event as obs_event

from agent.budget import BudgetExhausted, RequestBudget

_BOUNDED_MAX_WORKERS: int = 8
# Model calls are I/O-bound (network waits) and far more numerous than
# tool calls, so they get their own larger pool: streaming answer turns
# no longer pin the small tool pool, and vice versa.
_BOUNDED_MODEL_WORKERS: int = 32
# Queue bound: at most 2x workers may wait. Beyond that the server is
# saturated and callers must fail fast (ExecutorBusyError -> HTTP 503)
# instead of piling unbounded work into memory.
_BOUNDED_QUEUE_MULTIPLE: int = 2

logger = logging.getLogger(__name__)


class ExecutorBusyError(RuntimeError):
    """Raised when the bounded pool's queue is full: fail fast, retry later."""


class TokenStream:
    """Forward live model tokens; reset the consumer on supersede.

    One instance spans a user turn: pass it (or its __call__) as
    on_token to every final-answer invoke, and call reset_for_new_call
    before each new invoke. The first call streams uninterrupted; when
    a later call starts after tokens already flowed, the consumer is
    reset first so stale text is never concatenated with fresh text.
    Callback exceptions are swallowed (streaming is best-effort).
    """

    def __init__(
        self,
        on_token: Optional[Callable[[str], None]] = None,
        on_reset: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_token = on_token
        self._on_reset = on_reset
        self._emitted = False

    @property
    def streaming(self) -> bool:
        """Whether any consumer wants tokens (else skip all overhead)."""
        return self._on_token is not None

    def reset_for_new_call(self) -> None:
        """Reset the consumer if a previous call already emitted tokens."""
        if self.streaming and self._emitted:
            self._emitted = False
            if self._on_reset is not None:
                try:
                    self._on_reset()
                except Exception:
                    logger.debug("stream reset callback failed", exc_info=True)

    def __call__(self, cumulative_text: str) -> None:
        if not self.streaming:
            return
        self._emitted = True
        try:
            self._on_token(str(cumulative_text))
        except Exception:
            logger.debug("stream token callback failed", exc_info=True)


class _BoundedExecutor:
    """One shared pool of daemon threads for all bounded calls.

    concurrent.futures.ThreadPoolExecutor cannot make daemon threads and
    was previously constructed per call (one leaked thread per hang).
    This pool is created once: at most _BOUNDED_MAX_WORKERS threads ever
    exist, they are daemons (never block process exit), and each task
    reports through its own Future so a caller timeout orphans only the
    result, never a thread. A worker that raises never dies: exceptions
    are captured into the task's Future.
    """

    def __init__(self, max_workers: int, name: str) -> None:
        self._name = name
        self._tasks: "queue.Queue" = queue.Queue(maxsize=max(1, max_workers * _BOUNDED_QUEUE_MULTIPLE))
        self._threads: List[threading.Thread] = []
        for i in range(max_workers):
            thread = threading.Thread(
                target=self._serve, name=f"{name}-{i}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def _serve(self) -> None:
        while True:
            fn, future = self._tasks.get()
            try:
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    future.set_result(fn())
                except BaseException as exc:  # never kill a shared worker
                    future.set_exception(exc)
            finally:
                self._tasks.task_done()

    def submit(self, fn: Callable[[], Any]) -> "concurrent.futures.Future":
        """Queue fn for a pool worker; returns its Future immediately.

        Raises ExecutorBusyError when the bounded queue is full instead
        of queueing forever: the caller is saturated and must shed load.
        """
        future: concurrent.futures.Future = concurrent.futures.Future()
        try:
            self._tasks.put_nowait((fn, future))
        except queue.Full:
            raise ExecutorBusyError(
                f"Executor '{self._name}' is saturated; please retry in a moment."
            )
        return future


_bounded_pool = _BoundedExecutor(_BOUNDED_MAX_WORKERS, "pluto-bounded")
_bounded_model_pool = _BoundedExecutor(_BOUNDED_MODEL_WORKERS, "pluto-model")


def _call_bounded(fn: Callable[[], Any], timeout: float, what: str,
                  pool: Any = None) -> Any:
    """Run fn with a hard wall-clock bound on a daemon pool.

    pool defaults to the tool pool (historical behavior; the overload
    test swaps this name). Model calls pass the larger model pool.
    """
    future = (pool if pool is not None else _bounded_pool).submit(fn)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as e:
        # Since Python 3.11 concurrent.futures.TimeoutError IS the builtin
        # TimeoutError, a worker that raised its own TimeoutError (e.g. the
        # first-token deadline) lands here too. If the worker already
        # finished, re-raise its real outcome to preserve the message;
        # only a still-running worker means this call truly timed out.
        if future.done():
            return future.result()
        raise TimeoutError(f"{what} timed out after {timeout:g}s.") from e


def _first_token_timeout() -> float:
    """First-token deadline in seconds (0 disables streaming fast-fail)."""
    try:
        return max(
            0.0,
            float(
                os.environ.get(
                    "PLUTO_FIRST_TOKEN_TIMEOUT",
                    str(FIRST_TOKEN_TIMEOUT_SECONDS),
                )
            ),
        )
    except (TypeError, ValueError):
        return FIRST_TOKEN_TIMEOUT_SECONDS


def _first_token_timeout_for_tier(tier: Optional[str]) -> float:
    """Per-tier first-token deadline.

    OpenRouter free lanes queue longer; local Ollama needs longer still
    (cold model load / VRAM swap of multi-GB weights + thinking chains
    before the first token). Env overrides: PLUTO_FIRST_TOKEN_TIMEOUT,
    PLUTO_FIRST_TOKEN_TIMEOUT_OPENROUTER, PLUTO_FIRST_TOKEN_TIMEOUT_OLLAMA.
    """
    if tier and str(tier).lower().startswith("openrouter"):
        try:
            return max(
                0.0,
                float(
                    os.environ.get(
                        "PLUTO_FIRST_TOKEN_TIMEOUT_OPENROUTER",
                        str(FIRST_TOKEN_TIMEOUT_OPENROUTER_SECONDS),
                    )
                ),
            )
        except (TypeError, ValueError):
            return FIRST_TOKEN_TIMEOUT_OPENROUTER_SECONDS
    if tier and str(tier).lower().startswith("ollama"):
        try:
            return max(
                0.0,
                float(
                    os.environ.get(
                        "PLUTO_FIRST_TOKEN_TIMEOUT_OLLAMA",
                        str(FIRST_TOKEN_TIMEOUT_OLLAMA_SECONDS),
                    )
                ),
            )
        except (TypeError, ValueError):
            return FIRST_TOKEN_TIMEOUT_OLLAMA_SECONDS
    return _first_token_timeout()


def _next_chunk_before(iterator: Iterator[Any], deadline: float) -> Any:
    """Return next(iterator), raising TimeoutError past the deadline.

    The pull runs on a bounded throwaway daemon thread (never the shared
    pool: submitting pool work from inside a pool worker would deadlock).
    Concurrency is capped by a semaphore so a burst of slow providers
    can't spawn unbounded threads.
    """
    box: List[Any] = []
    errors: List[BaseException] = []
    if not hasattr(_next_chunk_before, "_sema"):
        import threading as _th

        _next_chunk_before._sema = _th.Semaphore(32)  # type: ignore[attr-defined]

    def _pull() -> None:
        try:
            box.append(next(iterator))
        except BaseException as exc:  # captured, re-raised below
            errors.append(exc)
        finally:
            try:
                _next_chunk_before._sema.release()  # type: ignore[attr-defined]
            except Exception:
                logger.debug("chunk semaphore release failed", exc_info=True)

    acquired = _next_chunk_before._sema.acquire(timeout=deadline)  # type: ignore[attr-defined]
    if not acquired:
        raise TimeoutError(
            f"Model request first token timed out after {deadline:g}s."
        )
    worker = threading.Thread(target=_pull, daemon=True)
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        raise TimeoutError(
            f"Model request first token timed out after {deadline:g}s."
        )
    if errors:
        exc = errors[0]
        if isinstance(exc, StopIteration):
            raise RuntimeError("Model returned no output.") from exc
        raise exc
    return box[0]


def _merge_stream_chunks(chunks: List[Any]) -> Any:
    """Fold streamed message chunks into one response (text + tool calls)."""
    merged = chunks[0]
    for chunk in chunks[1:]:
        try:
            merged = merged + chunk
        except Exception:
            # Keep already-streamed prefix instead of discarding it.
            logger.debug("stream chunk merge failed; keeping prefix", exc_info=True)
            continue
    return merged


def _invoke_via_stream(
    llm_instance: BaseLanguageModel,
    messages: Any,
    first_token_timeout: float,
    on_token: Optional[Callable[[str], None]] = None,
) -> Any:
    """Stream one model call with a first-token deadline.

    Returns the merged response, or None when streaming could not
    start (no .stream attribute, setup failure, first-chunk failure:
    legacy/test doubles or a provider that rejects streaming) — the
    caller then falls back to plain .invoke(). Those fallbacks are
    logged at debug (routine and benign).
    A silent provider raises TimeoutError so the cascade fails over.
    A failure AFTER the first chunk arrived propagates to the caller
    (fail over to the next tier): re-invoking the same request would
    double latency and provider load, and a rate limit would fail
    again anyway.
    When on_token is given it receives cumulative answer text per
    chunk (deduped: only on growth, so tool-call-only deltas stay
    silent); callback exceptions never break the invoke.
    """
    stream_fn = getattr(llm_instance, "stream", None)
    if not callable(stream_fn):
        return None
    try:
        iterator = stream_fn(messages)
    except Exception:
        logger.debug("stream setup failed, falling back to invoke", exc_info=True)
        return None

    def _emit(merged: Any, last_len: List[int]) -> None:
        if on_token is None:
            return
        try:
            text = _as_text(merged.content)
        except Exception:
            return
        if len(text) > last_len[0]:
            last_len[0] = len(text)
            try:
                on_token(text)
            except Exception:
                logger.debug("stream chunk callback failed", exc_info=True)

    try:
        first = _next_chunk_before(iterator, first_token_timeout)
    except TimeoutError:
        raise
    except Exception:
        logger.debug("first chunk failed, falling back to invoke", exc_info=True)
        return None
    chunks = [first]
    merged = first
    last_len = [0]
    _emit(merged, last_len)
    for chunk in iterator:
        chunks.append(chunk)
        try:
            merged = merged + chunk
        except Exception:
            logger.debug("chunk merge failed mid-stream", exc_info=True)
            merged = chunk
        _emit(merged, last_len)
    return _merge_stream_chunks(chunks)


def _invoke_bounded(
    llm_instance: BaseLanguageModel,
    messages: Any,
    timeout: float = MODEL_TIMEOUT_SECONDS,
    budget: Optional[RequestBudget] = None,
    on_token: Optional[Callable[[str], None]] = None,
    tier_name: Optional[str] = None,
) -> Any:
    """Invoke a model with bounded execution time, charging the budget.

    The call streams when the model supports it: silence past the
    first-token deadline raises TimeoutError (fast tier fallback),
    while the full answer still enjoys the total timeout. Models
    without streaming use plain invocation under the total timeout.
    on_token receives cumulative answer text live (see
    _invoke_via_stream); None keeps the historical silent behavior.
    Outgoing history is sanitized first: encrypted provider reasoning
    (bound to the issuing model/key) is stripped so cascade fallback
    to another tier never fails with "was not issued to this caller".
    tier_name selects the per-tier first-token budget (OpenRouter 20s).
    """
    try:
        messages = sanitize_messages_for_provider(messages)
    except Exception:
        logger.debug("provider history sanitize failed; sending as-is", exc_info=True)
    if budget is not None:
        try:
            budget.check_context(messages)
        except BudgetExhausted:
            raise
        except Exception:
            logger.debug("context budget check failed; proceeding", exc_info=True)
        budget.count_llm()
    provider = getattr(llm_instance, "model", type(llm_instance).__name__)
    first_token_timeout = _first_token_timeout_for_tier(tier_name) if tier_name else _first_token_timeout()

    def _call() -> Any:
        if first_token_timeout > 0:
            streamed = _invoke_via_stream(
                llm_instance, messages, first_token_timeout, on_token
            )
            if streamed is not None:
                return streamed
        return llm_instance.invoke(messages)

    def _record_outcome(response: Any, elapsed: float) -> Any:
        # Best-effort telemetry only: usage tokens (when the provider
        # returns usage_metadata — often absent on free tiers) and a
        # per-tier latency EMA for slow-tier demotion. Never raises.
        try:
            from services.metrics import LLM_TOKEN_USAGE
        except Exception:
            LLM_TOKEN_USAGE = None  # type: ignore[assignment]
        try:
            meta = getattr(response, "usage_metadata", None) or {}
            if isinstance(meta, dict) and LLM_TOKEN_USAGE is not None:
                prompt = int(meta.get("input_tokens", 0) or 0)
                completion = int(meta.get("output_tokens", 0) or 0)
                tier = str(tier_name or "unknown")
                if prompt > 0:
                    LLM_TOKEN_USAGE.labels(tier, "prompt").inc(prompt)
                if completion > 0:
                    LLM_TOKEN_USAGE.labels(tier, "completion").inc(completion)
        except Exception:
            logger.debug("token usage metric failed", exc_info=True)
        try:
            from agent.cascade import _record_latency

            _record_latency(str(tier_name or "unknown"), float(elapsed))
        except Exception:
            logger.debug("latency record failed", exc_info=True)
        return response

    started = time.monotonic()
    try:
        return _record_outcome(
            _call_bounded(_call, timeout, "Model request",
                          pool=_bounded_model_pool),
            time.monotonic() - started)
    except TimeoutError:
        if budget is not None:
            budget.timeouts += 1
        obs_event("llm.invoke", status="timeout", provider=str(provider), timeout_s=timeout)
        raise
    except Exception:
        obs_event("llm.invoke", status="error", provider=str(provider))
        raise
