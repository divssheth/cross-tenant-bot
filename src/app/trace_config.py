"""
Trace configuration for the cross-tenant Teams bot.

Supports two modes controlled by LOCAL_TRACING env var:
1. LOCAL_TRACING=true  → AI Toolkit / VS Code (OTLP on port 4317)
2. LOCAL_TRACING=false → Azure Monitor (APPLICATIONINSIGHTS_CONNECTION_STRING)

Uses Agent Framework's built-in observability which auto-instruments
agents, chat clients, and tool executions. See:
https://learn.microsoft.com/en-us/agent-framework/agents/observability
"""

import os
import logging
import contextvars
from typing import Optional

from opentelemetry import trace
from opentelemetry.trace import Tracer, NonRecordingSpan

# Monkey-patch: azure.ai.projects.telemetry._responses_instrumentor accesses
# span.span_instance.attributes, but NonRecordingSpan lacks that attribute
# (it only has set_attributes).  Adding a read-only property prevents the
# AttributeError crash inside the SDK.
if not hasattr(NonRecordingSpan, "attributes"):
    NonRecordingSpan.attributes = property(lambda self: {})

# Context variables for distributed tracing
trace_id: contextvars.ContextVar[str] = contextvars.ContextVar('trace_id', default='')
traceparent: contextvars.ContextVar[str] = contextvars.ContextVar('traceparent', default='')

_tracer: Optional[Tracer] = None
_initialized: bool = False

logger = logging.getLogger("cross-tenant-bot.trace")


def configure_telemetry() -> bool:
    """Configure telemetry based on environment.

    LOCAL_TRACING=true  → Agent Framework OTLP (AI Toolkit, port 4317)
    Otherwise           → Azure Monitor via configure_azure_monitor + enable_instrumentation

    Returns True if any telemetry provider was configured.
    """
    global _tracer, _initialized

    if _initialized:
        return True

    local_tracing = os.getenv("LOCAL_TRACING", "").lower() in ("true", "1", "yes")

    if local_tracing:
        ok = _configure_local()
    else:
        ok = _configure_azure_monitor()

    if ok:
        _tracer = trace.get_tracer(__name__)
        _initialized = True

    return ok


# ── Local development (AI Toolkit) ──────────────────────────────────────────

def _configure_local() -> bool:
    try:
        from agent_framework.observability import configure_otel_providers

        configure_otel_providers(
            vs_code_extension_port=4317,
            enable_sensitive_data=True,
        )
        logger.info("Agent Framework tracing configured (AI Toolkit, OTLP port 4317)")

        try:
            from azure.ai.projects.telemetry import AIProjectInstrumentor
            instrumentor = AIProjectInstrumentor()
            instrumentor.instrument(enable_content_recording=True)
            logger.info("AIProjectInstrumentor enabled (content recording on, instrumented=%s)", instrumentor.is_instrumented())
        except Exception as e:
            logger.warning("AIProjectInstrumentor failed: %s", e)

        return True
    except Exception as e:
        logger.error(f"Failed to configure local tracing: {e}")
        return False


# ── Azure Monitor (production) ──────────────────────────────────────────────

def _configure_azure_monitor() -> bool:
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.warning("APPLICATIONINSIGHTS_CONNECTION_STRING not set – telemetry disabled")
        return False

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from agent_framework.observability import create_resource, enable_instrumentation

        # Pattern #3 from the Agent Framework docs:
        # 1. Let Azure Monitor set up its providers (traces, logs, metrics)
        # 2. Then activate Agent Framework instrumentation code paths
        configure_azure_monitor(
            connection_string=connection_string,
            resource=create_resource(),
            logger_name="cross-tenant-bot",
            enable_live_metrics=True,
        )
        enable_instrumentation(enable_sensitive_data=False)

        try:
            from azure.ai.projects.telemetry import AIProjectInstrumentor
            instrumentor = AIProjectInstrumentor()
            instrumentor.instrument(enable_content_recording=False)
            logger.info("AIProjectInstrumentor enabled (content recording off, instrumented=%s)", instrumentor.is_instrumented())
        except Exception as e:
            logger.warning("AIProjectInstrumentor failed: %s", e)

        logger.info("Azure Monitor telemetry configured with Agent Framework instrumentation")
        return True
    except Exception as e:
        logger.error(f"Failed to configure Azure Monitor: {e}")
        return False


# ── Public helpers (used by other modules) ──────────────────────────────────

def get_tracer() -> Optional[Tracer]:
    """Return the OpenTelemetry tracer, or None if not initialized."""
    return _tracer


def is_telemetry_enabled() -> bool:
    """Return True if telemetry has been configured."""
    return _initialized
