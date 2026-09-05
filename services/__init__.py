"""Service layer: identity, storage, files, and request context.

UI code must go through these services instead of touching global
files or the working directory directly.
"""

from services.context import get_current_user_id, set_current_user_id
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
from services.storage import StorageError, UserStore

__all__ = [
    "FileStore",
    "FileValidationError",
    "MAX_CSV_ROWS",
    "MAX_PDF_PAGES",
    "MAX_SEARCH_CHARS",
    "MAX_UPLOAD_BYTES",
    "MODEL_TIMEOUT_SECONDS",
    "StorageError",
    "TOOL_TIMEOUT_SECONDS",
    "UserIdentity",
    "UserStore",
    "get_current_user",
    "get_current_user_id",
    "set_current_user_id",
]
