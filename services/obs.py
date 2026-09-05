"""Structured production diagnostics: timing + request/tool events.

Every event carries identifiers, counters, and durations ONLY — never
prompts, keys, tokens, document contents, memory, or payloads. Field
names hinting at credentials are dropped by _safe_fields() even if a
caller passes them by mistake. Operators collect stdlib logs; nothing
here changes user-facing messages.
"""

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger("poka.obs")

_FORBIDDEN_HINTS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "credential",
)


def _safe_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Strip credential-like fields; truncate overlong values."""
    clean: Dict[str, Any] = {}
    for key, value in fields.items():
        lowered = str(key).lower()
        if any(hint in lowered for hint in _FORBIDDEN_HINTS):
            continue
        if isinstance(value, str) and len(value) > 500:
            clean[key] = value[:500] + "...[truncated]"
        else:
            clean[key] = value
    return clean


def event(
    op: str,
    status: str = "ok",
    request_id: Optional[str] = None,
    duration_ms: Optional[float] = None,
    **fields: Any,
) -> None:
    """Emit one structured diagnostics event (metadata only)."""
    tail = ""
    if request_id:
        tail += f" req={request_id}"
    if duration_ms is not None:
        tail += f" {duration_ms:.1f}ms"
    logger.info("obs op=%s status=%s%s %s", op, status, tail, _safe_fields(fields))


@contextmanager
def timed(
    op: str,
    request_id: Optional[str] = None,
    **fields: Any,
) -> Iterator[Dict[str, Any]]:
    """Time a block and emit its obs event on exit.

    Yields a mutable record; set record["status"] before exit to
    override the default ("ok", or "error" when an exception escapes).
    Extra fields are metadata only (see _safe_fields).
    """
    record: Dict[str, Any] = {"status": "ok"}
    start = time.perf_counter()
    try:
        yield record
    except Exception:
        record["status"] = "error"
        raise
    finally:
        event(
            op,
            status=str(record.get("status", "ok")),
            request_id=request_id,
            duration_ms=(time.perf_counter() - start) * 1000.0,
            **fields,
        )
