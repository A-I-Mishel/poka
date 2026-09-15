"""FastAPI middleware: correlation IDs, metrics, tracing, access logs."""

import re
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from services.obs import record_http_request, set_active_connections
from services.structured_logging import bind_request_context, clear_request_context, get_logger
from services.tracing import SpanKind, Status, StatusCode, get_tracer

logger = get_logger("pluto.http")

# Collapse high-cardinality path segments (upload/artifact hex IDs, UUIDs)
# when no route template is available, so Prometheus label sets stay bounded.
_HEX_ID_RE = re.compile(r"/[0-9a-fA-F]{8,64}(?=/|$)")
_UUID_RE = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)")


def _endpoint_for(request: Request) -> str:
    """Stable endpoint label: route template when known, else sanitized path."""
    try:
        route = request.scope.get("route")
        template = getattr(route, "path", None)
        if template:
            return str(template)
    except Exception:
        pass
    try:
        path = request.url.path or "/"
    except Exception:
        return "/"
    path = _UUID_RE.sub("/:uuid", path)
    return _HEX_ID_RE.sub("/:id", path)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.tracer = get_tracer()

    async def dispatch(self, request: Request, call_next):
        # Correlation ID
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        user_id = getattr(request.state, "user_id", None) if hasattr(request, "state") else None
        bind_request_context(request_id, user_id)

        # Active connections
        set_active_connections(1)

        # Tracing
        span = self.tracer.start_span(
            f"HTTP {request.method} {request.url.path}",
            kind=SpanKind.SERVER,
            attributes={
                "http.method": request.method,
                "http.url": str(request.url),
                "http.scheme": request.url.scheme,
                "http.target": request.url.path,
                "pluto.request_id": request_id,
            },
        )

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            # Propagate trace context in response headers
            response.headers["X-Request-Id"] = request_id
            if span.is_recording():
                span.set_attribute("http.status_code", status_code)
            return response
        except Exception as e:
            if span.is_recording():
                try:
                    span.record_exception(e)
                except Exception:
                    pass
                span.set_status(Status(StatusCode.ERROR, str(e)[:300]))
            raise
        finally:
            duration = time.perf_counter() - start
            set_active_connections(-1)
            record_http_request(request.method, _endpoint_for(request), status_code, duration)

            # Access log (structured)
            logger.info(
                "http.request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": round(duration * 1000, 1),
                    "client_ip": request.client.host if request.client else "unknown",
                },
            )

            if span.is_recording():
                try:
                    span.end()
                except Exception:
                    pass
            clear_request_context()
