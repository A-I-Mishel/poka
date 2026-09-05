"""Service layer: identity, storage, files, and request context.

UI code must go through these services instead of touching global
files or the working directory directly.
"""

from services.auth import AuthRequired, AuthResult, auth_mode, authenticate, verify_access_token
from services.context import get_current_user_id, set_current_user_id
from services.context_budget import (
    CTX_CURRENT_TOKENS,
    CTX_EXTERNAL_TOKENS,
    CTX_HISTORY_TOKENS,
    CTX_MEMORY_TOKENS,
    CTX_SUMMARY_TOKENS,
    CTX_SYSTEM_TOKENS,
    CONTEXT_MAX_TOKENS,
    fit_history,
    fit_text,
)
from services.files import FileStore, FileValidationError
from services.identity import UserIdentity, get_current_user
from services.limits import (
    MAX_CSV_ROWS,
    MAX_PDF_PAGES,
    MAX_SEARCH_CHARS,
    MAX_UPLOAD_BYTES,
    MODEL_TIMEOUT_SECONDS,
    TOOL_TIMEOUT_SECONDS,
)
from services.ratelimit import MemoryRateLimiter, RateLimiter, RateLimitResult, configure_rate_limiter, get_rate_limiter
from services.storage import StorageError, UserStore
from services.tokens import count_tokens, truncate_tokens

__all__ = [
    "AuthRequired",
    "AuthResult",
    "CTX_CURRENT_TOKENS",
    "CTX_EXTERNAL_TOKENS",
    "CTX_HISTORY_TOKENS",
    "CTX_MEMORY_TOKENS",
    "CTX_SUMMARY_TOKENS",
    "CTX_SYSTEM_TOKENS",
    "CONTEXT_MAX_TOKENS",
    "FileStore",
    "FileValidationError",
    "MAX_CSV_ROWS",
    "MAX_PDF_PAGES",
    "MAX_SEARCH_CHARS",
    "MAX_UPLOAD_BYTES",
    "MODEL_TIMEOUT_SECONDS",
    "MemoryRateLimiter",
    "RateLimiter",
    "RateLimitResult",
    "StorageError",
    "TOOL_TIMEOUT_SECONDS",
    "UserIdentity",
    "UserStore",
    "auth_mode",
    "authenticate",
    "configure_rate_limiter",
    "count_tokens",
    "fit_history",
    "fit_text",
    "get_current_user",
    "get_current_user_id",
    "get_rate_limiter",
    "set_current_user_id",
    "truncate_tokens",
    "verify_access_token",
]
