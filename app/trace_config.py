"""
Trace configuration for request tracking.
"""
import contextvars

# Context variables for distributed tracing
trace_id: contextvars.ContextVar[str] = contextvars.ContextVar('trace_id', default='')
traceparent: contextvars.ContextVar[str] = contextvars.ContextVar('traceparent', default='')
