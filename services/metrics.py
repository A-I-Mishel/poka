"""Prometheus metrics for Pluto. All metrics are process-scoped (per worker).
For multi-process deployments, run a Prometheus Agent / Pushgateway sidecar.
"""

from prometheus_client import Counter, Histogram, Gauge, Info, CollectorRegistry

# ---- Registry (allows testing with isolated registry) ----
REGISTRY = CollectorRegistry()
METRICS_PREFIX = "pluto"

# ---- HTTP ----
HTTP_REQUEST_DURATION = Histogram(
    f"{METRICS_PREFIX}_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint", "status_code"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    registry=REGISTRY,
)
HTTP_REQUESTS_TOTAL = Counter(
    f"{METRICS_PREFIX}_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
    registry=REGISTRY,
)
HTTP_ACTIVE_CONNECTIONS = Gauge(
    f"{METRICS_PREFIX}_http_active_connections",
    "Currently active HTTP connections",
    registry=REGISTRY,
)

# ---- LLM Cascade ----
LLM_CALL_DURATION = Histogram(
    f"{METRICS_PREFIX}_llm_call_duration_seconds",
    "LLM call latency (successful calls only)",
    ["tier", "task_type"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 90),
    registry=REGISTRY,
)
LLM_TOKEN_USAGE = Counter(
    f"{METRICS_PREFIX}_llm_tokens_total",
    "Token usage by tier and direction",
    ["tier", "direction"],  # "prompt" | "completion"
    registry=REGISTRY,
)
LLM_TIER_FALLBACKS = Counter(
    f"{METRICS_PREFIX}_llm_tier_fallbacks_total",
    "Cascade fallbacks: requested_tier -> actual_tier",
    ["requested_tier", "actual_tier", "reason"],  # reason: rate_limit, timeout, auth, invalid, server, network
    registry=REGISTRY,
)
LLM_PROVIDER_ERRORS = Counter(
    f"{METRICS_PREFIX}_llm_provider_errors_total",
    "Provider errors by tier and error kind",
    ["tier", "error_kind"],  # from classify_provider_error
    registry=REGISTRY,
)
LLM_ACTIVE_TIER = Gauge(
    f"{METRICS_PREFIX}_llm_active_tier",
    "Current active tier per request (1=active, 0=inactive)",
    ["tier"],
    registry=REGISTRY,
)

# ---- Tools ----
TOOL_CALL_DURATION = Histogram(
    f"{METRICS_PREFIX}_tool_call_duration_seconds",
    "Tool execution latency",
    ["tool", "execution_mode"],  # "parallel" | "serial"
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    registry=REGISTRY,
)
TOOL_CALLS_TOTAL = Counter(
    f"{METRICS_PREFIX}_tool_calls_total",
    "Tool calls by outcome",
    ["tool", "status"],  # "ok" | "empty" | "failed" | "invalid" | "denied" | "degraded"
    registry=REGISTRY,
)
TOOL_PARALLEL_VS_SERIAL = Counter(
    f"{METRICS_PREFIX}_tool_parallel_vs_serial_total",
    "Tool execution mode",
    ["tool", "mode"],  # "parallel" | "serial"
    registry=REGISTRY,
)

# ---- Knowledge Base ----
KB_SEARCH_DURATION = Histogram(
    f"{METRICS_PREFIX}_kb_search_duration_seconds",
    "KB vector search latency",
    ["backend"],  # "faiss" | "brute_force" | "lexical"
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
    registry=REGISTRY,
)
KB_INDEX_SIZE = Gauge(
    f"{METRICS_PREFIX}_kb_index_size",
    "FAISS index size (number of vectors)",
    ["user_id"],
    registry=REGISTRY,
)
KB_CACHE_HITS = Counter(
    f"{METRICS_PREFIX}_kb_cache_hits_total",
    "KB cache hits/misses",
    ["result"],  # "hit" | "miss"
    registry=REGISTRY,
)
KB_INGEST_DURATION = Histogram(
    f"{METRICS_PREFIX}_kb_ingest_duration_seconds",
    "KB document ingest latency",
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60),
    registry=REGISTRY,
)

# ---- Storage ----
SQLITE_QUERY_DURATION = Histogram(
    f"{METRICS_PREFIX}_sqlite_query_duration_seconds",
    "SQLite query latency",
    ["operation"],  # "read" | "write" | "migration"
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
    registry=REGISTRY,
)
STORAGE_MIGRATION_STATUS = Gauge(
    f"{METRICS_PREFIX}_storage_migration_status",
    "Migration status per user (1=done, 0=pending, -1=failed)",
    ["user_id"],
    registry=REGISTRY,
)

# ---- Rate Limits ----
RATE_LIMIT_HITS = Counter(
    f"{METRICS_PREFIX}_rate_limit_hits_total",
    "Rate limit check allowed",
    ["action", "source"],  # source: "user" | "ip"
    registry=REGISTRY,
)
RATE_LIMIT_REJECTIONS = Counter(
    f"{METRICS_PREFIX}_rate_limit_rejections_total",
    "Rate limit check denied",
    ["action", "source"],
    registry=REGISTRY,
)
RATE_LIMIT_BUCKET_STATE = Gauge(
    f"{METRICS_PREFIX}_rate_limit_bucket_state",
    "Current bucket state",
    ["action", "identity", "metric"],  # metric: "used" | "remaining" | "limit"
    registry=REGISTRY,
)

# ---- Image Bridge (vision-to-text surrogate cache) ----
IMAGE_BRIDGE_EVENTS = Counter(
    f"{METRICS_PREFIX}_image_bridge_events_total",
    "Image bridge outcomes (cache hits/misses, conversions)",
    ["event"],  # "hit" | "miss" | "convert_ok" | "convert_failed"
    registry=REGISTRY,
)

# ---- Experience (self-improvement ledger) ----
LESSON_EVENTS = Counter(
    f"{METRICS_PREFIX}_lesson_events_total",
    "Self-improvement ledger events",
    ["event"],  # "episode" | "mined" | "trusted" | "applied"
    registry=REGISTRY,
)

# ---- Application Info ----
APP_INFO = Info(f"{METRICS_PREFIX}_app", "Application metadata", registry=REGISTRY)


def init_app_info(version: str = "0.1.0", commit: str = "unknown") -> None:
    """Initialize application info metric."""
    APP_INFO.info({"version": version, "commit": commit})
