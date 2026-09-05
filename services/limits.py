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

# Storage hygiene
MAX_FILENAME_LEN: int = 100
UPLOAD_ID_RE: str = r"^[0-9a-f]{16}$"
