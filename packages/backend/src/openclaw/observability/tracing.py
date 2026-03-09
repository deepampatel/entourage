"""Structured logging and trace context for distributed tracing.

Learn: Uses Python contextvars to propagate trace/span IDs through async
call chains without explicit parameter passing. Each request gets a trace_id
(32-char hex), and each operation within that request gets a span_id (16-char hex).

The StructuredJsonFormatter outputs JSON-lines format with trace context
included in every log entry, enabling log correlation across services.

Usage:
    trace = new_trace()
    span = new_span("pipeline.execute")
    log_structured(logger, logging.INFO, "pipeline started", pipeline_id="abc")
"""

import contextvars
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any


# ─── Context variables ──────────────────────────────────────

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)
span_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "span_id", default=""
)
operation_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "operation", default=""
)


# ─── Trace/span helpers ─────────────────────────────────────


def new_trace() -> str:
    """Generate a 32-char hex trace ID and set it in the contextvar.

    Learn: Trace IDs follow the W3C Trace Context format length (32 hex chars).
    Each high-level operation (HTTP request, pipeline run) gets a unique trace.
    """
    tid = uuid.uuid4().hex
    trace_id_var.set(tid)
    return tid


def new_span(op: str) -> str:
    """Create a 16-char hex span ID for a child operation.

    Learn: Spans represent units of work within a trace. The operation name
    is stored alongside the span for log context. Unlike full OTel, we keep
    it simple — no parent-child linking, just trace correlation.
    """
    sid = uuid.uuid4().hex[:16]
    span_id_var.set(sid)
    operation_var.set(op)
    return sid


def get_trace_context() -> dict[str, str]:
    """Return current trace context as a dict."""
    return {
        "trace_id": trace_id_var.get(""),
        "span_id": span_id_var.get(""),
        "op": operation_var.get(""),
    }


# ─── Structured JSON formatter ──────────────────────────────


class StructuredJsonFormatter(logging.Formatter):
    """JSON-lines log formatter with trace context.

    Learn: Each log line is a valid JSON object containing:
    - ts: ISO 8601 timestamp
    - level: log level name (INFO, WARNING, ERROR, etc.)
    - logger: logger name
    - trace_id, span_id, op: trace context from contextvars
    - msg: the log message
    - data: arbitrary key-value data (if any)

    Output example:
    {"ts":"2024-01-15T10:30:00Z","level":"INFO","logger":"openclaw","trace_id":"abc...","msg":"task started"}
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": trace_id_var.get(""),
            "span_id": span_id_var.get(""),
            "op": operation_var.get(""),
            "msg": record.getMessage(),
        }

        # Include extra data if present
        if hasattr(record, "structured_data") and record.structured_data:
            entry["data"] = record.structured_data

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


# ─── Structured log helper ──────────────────────────────────


def log_structured(
    logger: logging.Logger,
    level: int,
    msg: str,
    **data: Any,
) -> None:
    """Emit a structured log entry with arbitrary key-value data.

    Learn: Attaches extra data to the log record via a custom attribute
    (structured_data) that the StructuredJsonFormatter picks up.
    This avoids polluting the standard LogRecord namespace.

    Usage:
        log_structured(logger, logging.INFO, "task.dispatched",
                       task_id=42, agent_id="abc")
    """
    record = logger.makeRecord(
        name=logger.name,
        level=level,
        fn="",
        lno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    record.structured_data = data  # type: ignore[attr-defined]
    logger.handle(record)


# ─── Timer context manager ──────────────────────────────────


class SpanTimer:
    """Context manager that creates a span and measures duration.

    Usage:
        with SpanTimer("pipeline.execute") as timer:
            await do_work()
        print(timer.duration_ms)  # elapsed milliseconds
    """

    def __init__(self, operation: str):
        self.operation = operation
        self.span_id = ""
        self.start_time = 0.0
        self.duration_ms = 0.0

    def __enter__(self) -> "SpanTimer":
        self.span_id = new_span(self.operation)
        self.start_time = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.duration_ms = (time.monotonic() - self.start_time) * 1000
