"""Bounded invocation: every model/tool call runs under a deadline.

Design (see agent docstring for the cancellation model):
- Provider-native HTTP timeouts (config.py request_timeout) truly abort
  hung calls; this layer guarantees the caller regains control.
- ONE shared daemon-thread pool (_bounded_pool) backs all bounded calls:
  at most _BOUNDED_MAX_WORKERS threads ever exist, they never block
  process exit, and a caller timeout orphans only the result, never a
  thread. Never submit _call_bounded from inside a pool worker.
- Every model invocation also charges the request budget first.
"""

import concurrent.futures
import queue
import threading
from typing import Any, Callable, List, Optional

from langchain_core.language_models.base import BaseLanguageModel

from services.limits import MODEL_TIMEOUT_SECONDS
from services.obs import event as obs_event

from agent.budget import RequestBudget

_BOUNDED_MAX_WORKERS: int = 8


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
        self._tasks: "queue.Queue" = queue.Queue()
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
        """Queue fn for a pool worker; returns its Future immediately."""
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._tasks.put((fn, future))
        return future


_bounded_pool = _BoundedExecutor(_BOUNDED_MAX_WORKERS, "poka-bounded")


def _call_bounded(fn: Callable[[], Any], timeout: float, what: str) -> Any:
    """Run fn with a hard wall-clock bound on the shared daemon pool."""
    future = _bounded_pool.submit(fn)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as e:
        raise TimeoutError(f"{what} timed out after {timeout:g}s.") from e


def _invoke_bounded(
    llm_instance: BaseLanguageModel,
    messages: Any,
    timeout: float = MODEL_TIMEOUT_SECONDS,
    budget: Optional[RequestBudget] = None,
) -> Any:
    """Invoke a model with bounded execution time, charging the budget."""
    if budget is not None:
        budget.count_llm()
    provider = getattr(llm_instance, "model", type(llm_instance).__name__)
    try:
        return _call_bounded(lambda: llm_instance.invoke(messages), timeout, "Model request")
    except TimeoutError:
        if budget is not None:
            budget.timeouts += 1
        obs_event("llm.invoke", status="timeout", provider=str(provider), timeout_s=timeout)
        raise
    except Exception:
        obs_event("llm.invoke", status="error", provider=str(provider))
        raise
