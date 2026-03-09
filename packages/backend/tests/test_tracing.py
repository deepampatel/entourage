"""Tests for observability — tracing context, structured logging, middleware.

Covers: trace/span generation, JSON formatter, log_structured helper,
SpanTimer, and TracingMiddleware response headers.
"""

import json
import logging

import pytest


# ═══════════════════════════════════════════════════════════
# Trace context tests
# ═══════════════════════════════════════════════════════════


def test_new_trace_sets_contextvar():
    """new_trace() generates a 32-char hex ID and stores it in contextvar."""
    from openclaw.observability.tracing import new_trace, trace_id_var

    tid = new_trace()
    assert len(tid) == 32
    assert all(c in "0123456789abcdef" for c in tid)
    assert trace_id_var.get() == tid


def test_new_span_preserves_trace():
    """new_span() creates a new span but preserves the existing trace_id."""
    from openclaw.observability.tracing import (
        new_span,
        new_trace,
        operation_var,
        span_id_var,
        trace_id_var,
    )

    tid = new_trace()
    sid = new_span("test.operation")

    # Trace should be preserved
    assert trace_id_var.get() == tid
    # Span should be set
    assert span_id_var.get() == sid
    assert len(sid) == 16
    # Operation should be set
    assert operation_var.get() == "test.operation"


def test_new_span_changes_span_id():
    """Each new_span() call generates a different span_id."""
    from openclaw.observability.tracing import new_span, new_trace

    new_trace()
    s1 = new_span("op1")
    s2 = new_span("op2")
    assert s1 != s2


def test_get_trace_context():
    """get_trace_context() returns current trace/span/op as dict."""
    from openclaw.observability.tracing import get_trace_context, new_span, new_trace

    tid = new_trace()
    sid = new_span("check")
    ctx = get_trace_context()

    assert ctx["trace_id"] == tid
    assert ctx["span_id"] == sid
    assert ctx["op"] == "check"


# ═══════════════════════════════════════════════════════════
# Structured JSON formatter tests
# ═══════════════════════════════════════════════════════════


def test_structured_formatter_valid_json():
    """StructuredJsonFormatter outputs parseable JSON."""
    from openclaw.observability.tracing import StructuredJsonFormatter

    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Hello world",
        args=(),
        exc_info=None,
    )

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["msg"] == "Hello world"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test.logger"
    assert "ts" in parsed


def test_structured_formatter_includes_trace():
    """Formatter includes trace_id and span_id from contextvars."""
    from openclaw.observability.tracing import (
        StructuredJsonFormatter,
        new_span,
        new_trace,
    )

    tid = new_trace()
    sid = new_span("format.test")

    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0, msg="traced",
        args=(), exc_info=None,
    )

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["trace_id"] == tid
    assert parsed["span_id"] == sid
    assert parsed["op"] == "format.test"


def test_structured_formatter_with_data():
    """Formatter includes structured_data in 'data' key."""
    from openclaw.observability.tracing import StructuredJsonFormatter

    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0, msg="with data",
        args=(), exc_info=None,
    )
    record.structured_data = {"task_id": 42, "cost": 1.5}

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["data"]["task_id"] == 42
    assert parsed["data"]["cost"] == 1.5


def test_structured_formatter_no_data_key_when_empty():
    """Formatter omits 'data' key when no structured_data is set."""
    from openclaw.observability.tracing import StructuredJsonFormatter

    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0, msg="no data",
        args=(), exc_info=None,
    )

    output = formatter.format(record)
    parsed = json.loads(output)

    assert "data" not in parsed


# ═══════════════════════════════════════════════════════════
# log_structured helper tests
# ═══════════════════════════════════════════════════════════


def test_log_structured_with_data():
    """log_structured() attaches kwargs as structured_data on the record."""
    from openclaw.observability.tracing import StructuredJsonFormatter, log_structured

    test_logger = logging.getLogger("test.structured")
    test_logger.setLevel(logging.DEBUG)

    # Capture output
    handler = logging.StreamHandler()
    formatter = StructuredJsonFormatter()
    handler.setFormatter(formatter)

    captured = []
    original_emit = handler.emit

    def capture_emit(record):
        captured.append(formatter.format(record))

    handler.emit = capture_emit
    test_logger.addHandler(handler)

    try:
        log_structured(
            test_logger, logging.INFO, "task.dispatched",
            task_id=42, agent_id="abc123",
        )

        assert len(captured) == 1
        parsed = json.loads(captured[0])
        assert parsed["msg"] == "task.dispatched"
        assert parsed["data"]["task_id"] == 42
        assert parsed["data"]["agent_id"] == "abc123"
    finally:
        test_logger.removeHandler(handler)


# ═══════════════════════════════════════════════════════════
# SpanTimer tests
# ═══════════════════════════════════════════════════════════


def test_span_timer_measures_duration():
    """SpanTimer records elapsed time and sets span context."""
    import time

    from openclaw.observability.tracing import SpanTimer, new_trace, span_id_var

    new_trace()

    with SpanTimer("test.timer") as timer:
        time.sleep(0.01)  # 10ms

    assert timer.span_id != ""
    assert timer.duration_ms >= 5  # At least some time passed
    assert span_id_var.get() == timer.span_id


# ═══════════════════════════════════════════════════════════
# Middleware tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tracing_middleware_adds_headers(client):
    """TracingMiddleware adds X-Trace-ID and X-Request-Duration-Ms to response."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200

    # Check trace headers
    assert "X-Trace-ID" in resp.headers
    trace_id = resp.headers["X-Trace-ID"]
    assert len(trace_id) == 32
    assert all(c in "0123456789abcdef" for c in trace_id)

    assert "X-Request-Duration-Ms" in resp.headers
    duration = float(resp.headers["X-Request-Duration-Ms"])
    assert duration >= 0


@pytest.mark.asyncio
async def test_tracing_middleware_propagates_trace_id(client):
    """TracingMiddleware uses incoming X-Trace-ID header if provided."""
    custom_trace = "a" * 32
    resp = await client.get(
        "/api/v1/health",
        headers={"X-Trace-ID": custom_trace},
    )
    assert resp.headers["X-Trace-ID"] == custom_trace


@pytest.mark.asyncio
async def test_tracing_middleware_measures_duration(client):
    """X-Request-Duration-Ms is a positive float."""
    resp = await client.get("/api/v1/health")
    duration_str = resp.headers.get("X-Request-Duration-Ms", "0")
    duration = float(duration_str)
    assert duration >= 0
