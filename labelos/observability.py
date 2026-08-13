"""Structured logging helpers. Never log secrets."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

_SECRET_KEYS = {
    "authorization",
    "token",
    "api_token",
    "password",
    "secret",
    "labellos_api_token",
    "labelos_api_token",
}


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
    )


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in _SECRET_KEYS:
            redacted[key] = "***"
        elif isinstance(value, dict):
            redacted[key] = _redact(value)
        else:
            redacted[key] = value
    return redacted


def log_event(**fields: Any) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    logging.getLogger("labelos").info(json.dumps(_redact(payload), sort_keys=True, default=str))


@contextmanager
def log_operation(operation: str, **fields: Any) -> Iterator[dict[str, Any]]:
    started = time.perf_counter()
    context: dict[str, Any] = {"operation": operation, "status": "started", **fields}
    log_event(**context)
    try:
        yield context
        context["status"] = context.get("status", "ok")
    except Exception as error:
        context["status"] = "error"
        context["error_code"] = getattr(getattr(error, "error", None), "code", type(error).__name__)
        context["error"] = str(error)
        raise
    finally:
        context["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        log_event(**context)
