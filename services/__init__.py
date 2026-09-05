"""Service layer: identity, storage, files, and request context.

UI code must go through these services instead of touching global
files or the working directory directly.
"""

# Lazy re-exports (PEP 562) to avoid circular imports at package init.
# Submodule imports like `from services.auth import X` do NOT trigger
# these; they load the submodule directly. Only `from services import X`
# goes through __getattr__ below.
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

_LAZY = {
    "AuthRequired": ("services.identity", "AuthRequired"),
    "AuthResult": ("services.auth", "AuthResult"),
    "CTX_CURRENT_TOKENS": ("services.context_budget", "CTX_CURRENT_TOKENS"),
    "CTX_EXTERNAL_TOKENS": ("services.context_budget", "CTX_EXTERNAL_TOKENS"),
    "CTX_HISTORY_TOKENS": ("services.context_budget", "CTX_HISTORY_TOKENS"),
    "CTX_MEMORY_TOKENS": ("services.context_budget", "CTX_MEMORY_TOKENS"),
    "CTX_SUMMARY_TOKENS": ("services.context_budget", "CTX_SUMMARY_TOKENS"),
    "CTX_SYSTEM_TOKENS": ("services.context_budget", "CTX_SYSTEM_TOKENS"),
    "CONTEXT_MAX_TOKENS": ("services.context_budget", "CONTEXT_MAX_TOKENS"),
    "FileStore": ("services.files", "FileStore"),
    "FileValidationError": ("services.files", "FileValidationError"),
    "MAX_CSV_ROWS": ("services.limits", "MAX_CSV_ROWS"),
    "MAX_PDF_PAGES": ("services.limits", "MAX_PDF_PAGES"),
    "MAX_SEARCH_CHARS": ("services.limits", "MAX_SEARCH_CHARS"),
    "MAX_UPLOAD_BYTES": ("services.limits", "MAX_UPLOAD_BYTES"),
    "MODEL_TIMEOUT_SECONDS": ("services.limits", "MODEL_TIMEOUT_SECONDS"),
    "MemoryRateLimiter": ("services.ratelimit", "MemoryRateLimiter"),
    "RateLimiter": ("services.ratelimit", "RateLimiter"),
    "RateLimitResult": ("services.ratelimit", "RateLimitResult"),
    "StorageError": ("services.storage", "StorageError"),
    "TOOL_TIMEOUT_SECONDS": ("services.limits", "TOOL_TIMEOUT_SECONDS"),
    "UserIdentity": ("services.identity", "UserIdentity"),
    "UserStore": ("services.storage", "UserStore"),
    "auth_mode": ("services.identity", "auth_mode"),
    "authenticate": ("services.auth", "authenticate"),
    "configure_rate_limiter": ("services.ratelimit", "configure_rate_limiter"),
    "count_tokens": ("services.tokens", "count_tokens"),
    "fit_history": ("services.context_budget", "fit_history"),
    "fit_text": ("services.context_budget", "fit_text"),
    "get_current_user": ("services.identity", "get_current_user"),
    "get_current_user_id": ("services.context", "get_current_user_id"),
    "get_rate_limiter": ("services.ratelimit", "get_rate_limiter"),
    "set_current_user_id": ("services.context", "set_current_user_id"),
    "truncate_tokens": ("services.tokens", "truncate_tokens"),
    "verify_access_token": ("services.auth", "verify_access_token"),
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        mod_name, attr = _LAZY[name]
        mod = importlib.import_module(mod_name)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
