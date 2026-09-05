"""Centralized safety and resource limits.

Every magic number for uploads, tool output, and timeouts lives here so
behavior is consistent and easy to audit. No other module should hard-code
these values.
"""

# Uploads
MAX_UPLOAD_BYTES: int = 200 * 1024 * 1024
ALLOWED_UPLOAD_EXTS: frozenset = frozenset({"pdf", "csv", "png", "jpg", "jpeg"})

# Tool input/output caps
MAX_PDF_PAGES: int = 200
MAX_PDF_CHARS: int = 12000
MAX_CSV_ROWS: int = 50000
MAX_SEARCH_CHARS: int = 6000

# Execution bounds (seconds)
MODEL_TIMEOUT_SECONDS: float = 90.0
TOOL_TIMEOUT_SECONDS: float = 90.0
PROBE_TIMEOUT_SECONDS: float = 20.0

# Request budgets (per single user message)
MAX_LLM_CALLS_PER_REQUEST: int = 12
MAX_TOOL_CALLS_PER_REQUEST: int = 8
MAX_SEARCH_CALLS_PER_REQUEST: int = 2
MAX_REFLECTION_CALLS: int = 1
MAX_PLANNING_CALLS: int = 1
MAX_TOTAL_REQUEST_TIME: float = 300.0

# Context budgets (tokens, approximated — see services.tokens)
CONTEXT_MAX_TOKENS: int = 24000
CTX_HISTORY_TOKENS: int = 6000
CTX_MEMORY_TOKENS: int = 2000
CTX_SUMMARY_TOKENS: int = 2000
CTX_EXTERNAL_TOKENS: int = 4000
MAX_TOOL_RESULT_TOKENS: int = 3000
MAX_EXTERNAL_TOKENS: int = 12000
MAX_QUERY_CHARS: int = 300

# Rate limits: action -> (max calls, window seconds), scoped per user
RATE_LIMITS: dict = {
    "chat": (100, 3600.0),
    "search": (60, 3600.0),
    "upload": (30, 3600.0),
    "generate": (20, 3600.0),
    "deep": (20, 3600.0),
}

# Storage hygiene
MAX_FILENAME_LEN: int = 100
UPLOAD_ID_RE: str = r"^[0-9a-f]{16}$"
