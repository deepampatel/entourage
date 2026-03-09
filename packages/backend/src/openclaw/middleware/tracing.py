"""Tracing middleware — distributed trace propagation for HTTP requests.

Learn: Sets trace_id from the incoming X-Trace-ID header (for cross-service
tracing) or generates a new one. Measures request duration and adds both
X-Trace-ID and X-Request-Duration-Ms to the response headers.

This complements the existing RequestIdMiddleware by adding trace-level
context that spans across services (vs request-level IDs which are per-service).
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from openclaw.observability.tracing import (
    log_structured,
    new_span,
    new_trace,
    trace_id_var,
)

import logging

logger = logging.getLogger("openclaw.middleware.tracing")


class TracingMiddleware(BaseHTTPMiddleware):
    """Propagate distributed trace context and measure request duration.

    Learn: Starlette middleware wraps each request. We set trace context
    at the start so all downstream log entries include the trace_id.
    Duration is measured wall-clock (not CPU) for realistic latency tracking.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Use existing trace ID from header or generate new one
        incoming_trace = request.headers.get("X-Trace-ID", "")
        if incoming_trace:
            trace_id_var.set(incoming_trace)
            trace_id = incoming_trace
        else:
            trace_id = new_trace()

        # Create a span for this request
        new_span("http.request")

        start = time.monotonic()

        log_structured(
            logger,
            logging.INFO,
            "request.start",
            method=request.method,
            path=str(request.url.path),
            query=str(request.url.query) if request.url.query else "",
        )

        response: Response = await call_next(request)

        duration_ms = (time.monotonic() - start) * 1000

        # Add trace headers to response
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Request-Duration-Ms"] = f"{duration_ms:.1f}"

        log_structured(
            logger,
            logging.INFO,
            "request.end",
            method=request.method,
            path=str(request.url.path),
            status=response.status_code,
            duration_ms=round(duration_ms, 1),
        )

        return response
