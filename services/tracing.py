"""OpenTelemetry tracing setup. Spans: HTTP → cascade → LLM → tools.
All spans carry: tier, task_type, request_id, user_id (hashed), tokens, latency.
"""

import logging
from typing import Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.trace import SpanKind, Status, StatusCode

logger = logging.getLogger(__name__)

# Global tracer
_tracer: Optional[trace.Tracer] = None
_initialized = False


def init_tracing(service_name: str = "pluto-api", endpoint: Optional[str] = None) -> trace.Tracer:
    """Initialize OpenTelemetry. Call once at startup. Never raises.

    Production rules:
    - No OTLP endpoint -> NoOp exporter (never console in prod; console
      spills span attrs to stdout and breaks hermetic tests).
    - Console exporter only when OTEL_TRACES_EXPORTER=console explicitly.
    - Auto-instrumentation is best-effort; failures only warn.
    - Resolving endpoint from OTEL_EXPORTER_OTLP_ENDPOINT env when not passed.
    """
    global _tracer, _initialized
    if _initialized:
        # _tracer is always set when _initialized is True
        assert _tracer is not None
        return _tracer

    try:
        from services.secrets import get_secret

        resolved = (endpoint or get_secret("OTEL_EXPORTER_OTLP_ENDPOINT", "") or "").strip() or None
        resource = Resource.create({SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)

        exporter = None
        if resolved:
            try:
                exporter = OTLPSpanExporter(endpoint=resolved, insecure=True)
            except Exception:
                logger.warning("OTLP exporter init failed; tracing disabled", exc_info=True)
                exporter = None
        else:
            # Explicit opt-in console only; default is NoOp to avoid stdout spam.
            if (get_secret("OTEL_TRACES_EXPORTER", "") or "").strip().lower() == "console":
                try:
                    exporter = ConsoleSpanExporter()
                except Exception:
                    exporter = None

        if exporter is not None:
            try:
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except Exception:
                logger.warning("span processor init failed", exc_info=True)

        try:
            trace.set_tracer_provider(provider)
        except Exception:
            # Provider already set (e.g. tests import twice) — keep going.
            logger.debug("tracer provider already set", exc_info=True)
        try:
            _tracer = trace.get_tracer(__name__)
        except Exception:
            logger.warning("get_tracer failed; using NoOp", exc_info=True)
            _tracer = trace.NoOpTracer()

        # Auto-instrument (instance API for 0.65b0+; all best-effort).
        for _name, _fn in (
            ("fastapi", lambda: FastAPIInstrumentor().instrument()),
            ("httpx", lambda: HTTPXClientInstrumentor().instrument()),
            ("redis", lambda: RedisInstrumentor().instrument()),
            ("sqlite3", lambda: SQLite3Instrumentor().instrument()),
        ):
            try:
                _fn()
            except Exception:
                logger.debug("otel %s instrumentation skipped", _name, exc_info=True)

        _initialized = True
        logger.info("OpenTelemetry tracing initialized (endpoint=%s)", resolved or "noop")
        assert _tracer is not None
        return _tracer
    except Exception:
        # Tracing must never break requests/startup. Fall back to NoOp.
        logger.warning("tracing init failed; using NoOpTracer", exc_info=True)
        try:
            _tracer = trace.NoOpTracer()
        except Exception:
            # Last resort: proxy that returns NoOp spans.
            from opentelemetry.trace import NoOpTracer as _NoOp

            _tracer = _NoOp()
        _initialized = True
        assert _tracer is not None
        return _tracer


def get_tracer() -> trace.Tracer:
    if _tracer is None:
        try:
            return init_tracing()
        except Exception:
            logger.warning("get_tracer fallback to NoOp", exc_info=True)
            return trace.NoOpTracer()
    return _tracer


def _noop_span() -> trace.Span:
    """Return a NoOp span that safely absorbs set_attribute/end calls."""
    try:
        return trace.NoOpTracer().start_span("pluto.noop")
    except Exception:
        # Absolute last resort: minimal duck-type span.
        class _Span:
            def set_attribute(self, *a, **k):
                pass

            def set_status(self, *a, **k):
                pass

            def record_exception(self, *a, **k):
                pass

            def end(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Span()  # type: ignore[return-value]


# ---- Span helpers for cascade ----

def start_cascade_span(request_id: str, task_type: str, tier: Optional[str] = None) -> trace.Span:
    """Start a span for one cascade attempt. Never raises."""
    try:
        tracer = get_tracer()
        span = tracer.start_span(
            f"cascade.{tier or 'select'}",
            kind=SpanKind.CLIENT,
            attributes={
                "pluto.request_id": request_id,
                "pluto.task_type": task_type,
                "pluto.tier": tier or "auto",
            },
        )
        return span
    except Exception:
        return _noop_span()


def start_llm_span(request_id: str, tier: str, task_type: str, prompt_tokens: int = 0) -> trace.Span:
    """Start span for LLM call. Never raises."""
    try:
        tracer = get_tracer()
        span = tracer.start_span(
            f"llm.call.{tier}",
            kind=SpanKind.CLIENT,
            attributes={
                "pluto.request_id": request_id,
                "pluto.tier": tier,
                "pluto.task_type": task_type,
                "pluto.prompt_tokens": prompt_tokens,
                "gen_ai.system": _get_gen_ai_system(tier),
                "gen_ai.request.model": tier,
            },
        )
        return span
    except Exception:
        return _noop_span()


def _get_gen_ai_system(tier: str) -> str:
    """Determine gen_ai.system from tier name."""
    tier_lower = tier.lower()
    if any(x in tier_lower for x in ["openai", "groq", "cerebras", "github", "mistral", "nvidia", "openrouter"]):
        return "openai"
    return "gemini"


def end_llm_span(span: trace.Span, completion_tokens: int = 0, error: Optional[Exception] = None) -> None:
    """End LLM span with token counts and error status. Never raises."""
    if span is None:
        return
    try:
        span.set_attribute("pluto.completion_tokens", completion_tokens)
        if error:
            span.set_status(Status(StatusCode.ERROR, str(error)))
            try:
                span.record_exception(error)
            except Exception:
                logger.debug("span record_exception failed", exc_info=True)
        else:
            span.set_status(Status(StatusCode.OK))
        span.end()
    except Exception:
        logger.debug("end_llm_span failed", exc_info=True)


def start_tool_span(request_id: str, tool: str, execution_mode: str) -> trace.Span:
    """Start span for tool execution. Never raises."""
    try:
        tracer = get_tracer()
        span = tracer.start_span(
            f"tool.{tool}",
            kind=SpanKind.INTERNAL,
            attributes={
                "pluto.request_id": request_id,
                "pluto.tool": tool,
                "pluto.execution_mode": execution_mode,
            },
        )
        return span
    except Exception:
        return _noop_span()


def start_kb_span(request_id: str, operation: str, backend: str) -> trace.Span:
    """Start span for KB operation. Never raises."""
    try:
        tracer = get_tracer()
        span = tracer.start_span(
            f"kb.{operation}",
            kind=SpanKind.INTERNAL,
            attributes={
                "pluto.request_id": request_id,
                "pluto.kb.operation": operation,
                "pluto.kb.backend": backend,
            },
        )
        return span
    except Exception:
        return _noop_span()


def start_storage_span(request_id: str, operation: str) -> trace.Span:
    """Start span for storage operation. Never raises."""
    try:
        tracer = get_tracer()
        span = tracer.start_span(
            f"storage.{operation}",
            kind=SpanKind.INTERNAL,
            attributes={
                "pluto.request_id": request_id,
                "pluto.storage.operation": operation,
            },
        )
        return span
    except Exception:
        return _noop_span()
