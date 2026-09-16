"""Unified observability facade: metrics + tracing + structured logs.
Thin wrappers — all heavy lifting delegated to specialized modules.
"""

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from services.metrics import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_TOTAL,
    HTTP_ACTIVE_CONNECTIONS,
    LLM_CALL_DURATION,
    LLM_TOKEN_USAGE,
    LLM_TIER_FALLBACKS,
    LLM_PROVIDER_ERRORS,
    TOOL_CALL_DURATION,
    TOOL_CALLS_TOTAL,
    TOOL_PARALLEL_VS_SERIAL,
    KB_SEARCH_DURATION,
    KB_INDEX_SIZE,
    KB_CACHE_HITS,
    KB_INGEST_DURATION,
    SQLITE_QUERY_DURATION,
    STORAGE_MIGRATION_STATUS,
    RATE_LIMIT_HITS,
    RATE_LIMIT_REJECTIONS,
    RATE_LIMIT_BUCKET_STATE,
)
from services.tracing import (
    start_llm_span,
    end_llm_span,
    start_tool_span,
    start_kb_span,
    start_storage_span,
)
from services.structured_logging import get_logger

logger = get_logger("pluto.obs")


# ---- HTTP ----
def record_http_request(method: str, endpoint: str, status_code: int, duration_s: float) -> None:
    HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint, status_code=str(status_code)).observe(duration_s)
    HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status_code=str(status_code)).inc()


def set_active_connections(delta: int) -> None:
    """Adjust the active-connections gauge by delta (+1 on entry, -1 on exit)."""
    HTTP_ACTIVE_CONNECTIONS.inc(delta)


# ---- LLM ----
@contextmanager
def trace_llm_call(request_id: str, tier: str, task_type: str, prompt_tokens: int = 0):
    try:
        span = start_llm_span(request_id, tier, task_type, prompt_tokens)
    except Exception:
        span = None
    start = time.perf_counter()
    _completion = [0]
    error = None

    def _set_completion(tokens: int) -> None:
        try:
            _completion[0] = int(tokens or 0)
        except Exception:
            pass

    try:
        yield _set_completion
    except Exception as e:
        error = e
        try:
            LLM_PROVIDER_ERRORS.labels(tier=tier, error_kind=type(e).__name__).inc()
        except Exception:
            pass
        raise
    finally:
        try:
            duration = time.perf_counter() - start
            LLM_CALL_DURATION.labels(tier=tier, task_type=task_type).observe(duration)
            if _completion[0]:
                LLM_TOKEN_USAGE.labels(tier=tier, direction="completion").inc(_completion[0])
            if prompt_tokens:
                LLM_TOKEN_USAGE.labels(tier=tier, direction="prompt").inc(prompt_tokens)
        except Exception:
            pass
        try:
            if span is not None:
                end_llm_span(span, _completion[0], error)
        except Exception:
            pass


def record_tier_fallback(requested: str, actual: str, reason: str) -> None:
    LLM_TIER_FALLBACKS.labels(requested_tier=requested, actual_tier=actual, reason=reason).inc()


def record_provider_error(tier: str, error_kind: str) -> None:
    LLM_PROVIDER_ERRORS.labels(tier=tier, error_kind=error_kind).inc()


# ---- Tools ----
@contextmanager
def trace_tool_call(request_id: str, tool: str, execution_mode: str):
    try:
        span = start_tool_span(request_id, tool, execution_mode)
    except Exception:
        span = None
    start = time.perf_counter()
    status = "ok"
    try:
        yield
    except Exception:
        status = "failed"
        raise
    finally:
        try:
            duration = time.perf_counter() - start
            TOOL_CALL_DURATION.labels(tool=tool, execution_mode=execution_mode).observe(duration)
            TOOL_CALLS_TOTAL.labels(tool=tool, status=status).inc()
        except Exception:
            pass
        try:
            if span is not None:
                span.end()
        except Exception:
            pass


def record_tool_execution_mode(tool: str, mode: str) -> None:
    TOOL_PARALLEL_VS_SERIAL.labels(tool=tool, mode=mode).inc()


# ---- KB ----
@contextmanager
def trace_kb_search(request_id: str, backend: str):
    try:
        span = start_kb_span(request_id, "search", backend)
    except Exception:
        span = None
    start = time.perf_counter()
    try:
        yield
    finally:
        try:
            duration = time.perf_counter() - start
            KB_SEARCH_DURATION.labels(backend=backend).observe(duration)
        except Exception:
            pass
        try:
            if span is not None:
                span.end()
        except Exception:
            pass


def record_kb_cache_hit(hit: bool) -> None:
    KB_CACHE_HITS.labels(result="hit" if hit else "miss").inc()


def set_kb_index_size(user_id: str, size: int) -> None:
    KB_INDEX_SIZE.labels(user_id=user_id).set(size)


@contextmanager
def trace_kb_ingest():
    start = time.perf_counter()
    try:
        yield
    finally:
        KB_INGEST_DURATION.observe(time.perf_counter() - start)


# ---- Storage ----
@contextmanager
def trace_sqlite_query(operation: str):
    try:
        span = start_storage_span("request", operation)
    except Exception:
        span = None
    start = time.perf_counter()
    try:
        yield
    finally:
        try:
            duration = time.perf_counter() - start
            SQLITE_QUERY_DURATION.labels(operation=operation).observe(duration)
        except Exception:
            pass
        try:
            if span is not None:
                span.end()
        except Exception:
            pass


def set_migration_status(user_id: str, status: int) -> None:  # 1=done, 0=pending, -1=failed
    STORAGE_MIGRATION_STATUS.labels(user_id=user_id).set(status)


# ---- Rate Limits ----
def record_rate_limit_hit(action: str, source: str) -> None:
    RATE_LIMIT_HITS.labels(action=action, source=source).inc()


def record_rate_limit_rejection(action: str, source: str) -> None:
    RATE_LIMIT_REJECTIONS.labels(action=action, source=source).inc()


def set_rate_limit_bucket_state(action: str, identity: str, used: int, remaining: int, limit: int) -> None:
    RATE_LIMIT_BUCKET_STATE.labels(action=action, identity=identity, metric="used").set(used)
    RATE_LIMIT_BUCKET_STATE.labels(action=action, identity=identity, metric="remaining").set(remaining)
    RATE_LIMIT_BUCKET_STATE.labels(action=action, identity=identity, metric="limit").set(limit)


# ---- Legacy event() compatibility ----
def event(op: str, status: str = "ok", request_id: Optional[str] = None, duration_ms: Optional[float] = None, **fields: Any) -> None:
    """Backward-compatible event emitter (structured log)."""
    logger.info("obs", extra={"op": op, "status": status, "request_id": request_id, "duration_ms": duration_ms, **fields})


@contextmanager
def timed(op: str, request_id: Optional[str] = None, **fields: Any) -> Iterator[Dict[str, Any]]:
    """Time a block; emit event on exit."""
    record: Dict[str, Any] = {"status": "ok"}
    start = time.perf_counter()
    try:
        yield record
    except Exception:
        record["status"] = "error"
        raise
    finally:
        event(op, status=str(record.get("status", "ok")), request_id=request_id, duration_ms=(time.perf_counter() - start) * 1000.0, **fields)
