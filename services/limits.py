"""Centralized safety and resource limits.

Every magic number for uploads, tool output, and timeouts lives here so
behavior is consistent and easy to audit. No other module should hard-code
these values.
"""

# Uploads
MAX_UPLOAD_BYTES: int = 200 * 1024 * 1024
ALLOWED_UPLOAD_EXTS: frozenset = frozenset({"pdf", "csv", "png", "jpg", "jpeg"})

# Per-user storage exhaustion controls (checked BEFORE writes/parsing).
MAX_UPLOADS_PER_USER: int = 100
MAX_USER_BYTES: int = 1024 * 1024 * 1024
MAX_OUTPUT_AGE_DAYS: int = 30

# CSV parse guards (all checked BEFORE pandas runs).
MAX_CSV_COLUMNS: int = 1000
MAX_CSV_PARSE_BYTES: int = 25 * 1024 * 1024

# Presentation generation guard (checked BEFORE expensive building).
MAX_PPTX_SLIDES: int = 50
MAX_PPTX_BULLETS_PER_SLIDE: int = 200

# Document generation guard (checked BEFORE expensive building).
MAX_DOCX_PARAGRAPHS: int = 1000

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

# Project context (explicit user-controlled per-project text).
# Conservative: operational instructions, not a document store (~1000
# tokens against a 24k budget alongside memory and history).
MAX_PROJECT_CONTEXT_CHARS: int = 4000

# Research brief bounds (user-owned research records).
MAX_BRIEF_QUERY_CHARS: int = 500
MAX_BRIEF_EXCERPT_CHARS: int = 4000

# Generation spec bounds (opaque reproducibility records, never code).
# Per-string and total caps keep specs from becoming a document store.
MAX_SPEC_STRING_CHARS: int = 100_000
MAX_SPEC_TOTAL_CHARS: int = 200_000

# Storage hygiene
MAX_FILENAME_LEN: int = 100
UPLOAD_ID_RE: str = r"^[0-9a-f]{16}$"

# Composer attachments (per single user message). 5 total keeps tool
# hints small (contents are never stuffed; tools read on demand within
# existing budgets) with headroom under the 8-record storage backstop.
# Images are capped at 3 to match the vision fast-path batch size.
MAX_ATTACHMENTS_PER_MESSAGE: int = 5
MAX_IMAGE_ATTACHMENTS: int = 3

# UI display truncations (single source of truth — no [:38]/[:120]/[:200]
# literals elsewhere in production code; tests may use literals).
MAX_CHAT_TITLE_CHARS: int = 38
MAX_DISPLAY_NAME_CHARS: int = 120
MAX_ERROR_SNIPPET_CHARS: int = 200

# Structured presentation builder bounds (single source of truth).
# create_pptx caps via MAX_PPTX_SLIDES / MAX_PPTX_BULLETS_PER_SLIDE above;
# build_presentation reuses the same slide cap plus these layout caps.
PPTX_BUILD_MAX_TITLE_CHARS: int = 80
PPTX_BUILD_MAX_BULLET_CHARS: int = 160
PPTX_BUILD_MAX_BULLETS_PER_CHUNK: int = 7
PPTX_BUILD_MAX_TABLE_ROWS: int = 12
PPTX_BUILD_MAX_TABLE_COLS: int = 6
PPTX_BUILD_MAX_SUBTITLE_CHARS: int = 120

# UI layout dimensions (Streamlit API ints — CSS strings live in
# ui/theme/tokens.py). Single source of truth for width=/height= literals.
UI_IMAGE_PREVIEW_WIDTH: int = 320
UI_TEXT_AREA_HEIGHT: int = 80
UI_HTML_SHIM_HEIGHT: int = 0
