"""Observability — structured logging and distributed tracing.

Learn: All trace context (trace_id, span_id, operation) is stored in
contextvars so it automatically propagates through async call chains.
The StructuredJsonFormatter emits JSON-lines logs with trace context
for machine-parseable log aggregation.
"""
