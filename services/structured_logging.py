"""Structured JSON logging with correlation IDs.
Middleware injects X-Request-Id; all logs in the request carry it.
"""

import logging
import sys
import uuid
from contextvars import ContextVar
from pythonjsonlogger import jsonlogger
from typing import Optional

# Context variable for correlation ID (works across async/threads)
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("user_id", default=None)


class PlutoJsonFormatter(jsonlogger.JsonFormatter):
    """JSON log formatter with correlation IDs and standard fields."""

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict):
        super().add_fields(log_record, record, message_dict)
        # Standard fields
        log_record["timestamp"] = self.formatTime(record, self.datefmt)
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        # Correlation IDs
        req_id = request_id_var.get()
        if req_id:
            log_record["request_id"] = req_id
        user_id = user_id_var.get()
        if user_id:
            log_record["user_id"] = user_id
        # Exception info
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)


def configure_structured_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure root logger. Call once at startup."""
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        formatter = PlutoJsonFormatter(
            fmt="%(timestamp)s %(level)s %(logger)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S.%fZ",
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S.%fZ",
        )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Silence noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx._client").setLevel(logging.WARNING)


def bind_request_context(request_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
    """Bind correlation IDs for current context (call in middleware)."""
    if request_id is None:
        request_id = uuid.uuid4().hex[:12]
    request_id_var.set(request_id)
    if user_id:
        user_id_var.set(user_id)
    return request_id


def clear_request_context() -> None:
    request_id_var.set(None)
    user_id_var.set(None)


def get_logger(name: str) -> logging.Logger:
    """Get a logger that inherits structured config."""
    return logging.getLogger(name)
