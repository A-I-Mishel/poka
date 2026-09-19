"""Stable IDs, registry constants, and storage exceptions.

Leaf module: no imports from sibling storage submodules (paths/io/
cleaners/store all build on this).
"""

import re
import uuid
from typing import Any, Dict

MAX_STORED_CHATS: int = 50
MAX_MSGS_PER_CHAT: int = 100
# Attachment kinds that survive clean_messages. Must cover every kind
# services.files.kind_for_ext() can produce (pdf/csv/image/document) —
# anything missing here is silently stripped from history on every save,
# which also breaks retention references and regenerate for that kind.
ATTACH_KINDS = ("pdf", "csv", "image", "document")
MAX_PROJECT_NAME_LEN: int = 60
PROJECTS_VERSION: int = 1

_ID16_RE = re.compile(r"^[0-9a-f]{16}$")


def is_valid_id(value: Any) -> bool:
    """True for stable 16-hex IDs (conversations, projects, uploads)."""
    return isinstance(value, str) and _ID16_RE.match(value) is not None


def new_conversation_id() -> str:
    """Generate a fresh stable conversation/project ID."""
    return uuid.uuid4().hex[:16]


RESPONSE_MODES = ("fast", "deep")
MAX_MODEL_NAME_LEN: int = 64
MAX_TOOL_NAMES: int = 20
MAX_TOOL_NAME_LEN: int = 64
MAX_SOURCES: int = 6
MAX_SOURCE_TITLE_LEN: int = 120
MAX_SOURCE_URL_LEN: int = 500
MAX_SOURCE_DOMAIN_LEN: int = 120
_SOURCE_URL_SCHEMES = ("http", "https")

# Generation-spec tool allowlist: tool name -> (artifact kind, exact
# permitted input keys). Specs reproduce tool calls; anything outside
# this table is not a valid spec.
_SPEC_TOOLS: Dict[str, Any] = {
    "create_pptx": ("pptx", {"topic", "content"}),
    "build_presentation": ("pptx", {"spec_json"}),
    "create_docx": ("docx", {"title", "content"}),
    "build_document": ("docx", {"title", "markdown_text"}),
    "create_pdf": ("pdf", {"title", "markdown_text"}),
    "create_markdown": ("md", {"title", "markdown_text"}),
    "create_doc": ("doc", {"title", "markdown_text"}),
    "create_html": ("html", {"title", "html_content"}),
}


class StorageError(Exception):
    """Raised when a storage path or operation is unsafe or fails."""


class WorkflowNotFoundError(ValueError):
    """Unknown workflow ID (distinct from invalid definitions)."""
