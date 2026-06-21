"""Structured logging utilities."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from app.core.config import Settings

_request_id: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str):
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)


class JsonFormatter(logging.Formatter):
    """Convert log records into JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Return JSON-serialized log payload."""

        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            payload["request_id"] = request_id
        if hasattr(record, "context"):
            payload["context"] = record.context
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


class RequestIdFilter(logging.Filter):
    """Attach the current request ID to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True


def configure_logging(settings: Settings) -> None:
    """Initialize root logger based on settings."""

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.logging.level.upper())
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if settings.logging.json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(request_id)s | %(message)s")
        )
    root.addHandler(handler)
