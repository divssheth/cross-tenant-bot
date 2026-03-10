"""
Trace configuration for request tracking with OpenTelemetry.

Supports two modes:
1. Azure Monitor - for production (APPLICATIONINSIGHTS_CONNECTION_STRING)
2. AI Toolkit - for local development (configure_agent_framework_tracing)
"""
import os
import logging
import contextvars
from typing import Optional

from opentelemetry import trace
from opentelemetry.trace import Tracer

# Context variables for distributed tracing
trace_id: contextvars.ContextVar[str] = contextvars.ContextVar('trace_id', default='')
traceparent: contextvars.ContextVar[str] = contextvars.ContextVar('traceparent', default='')

# Module-level tracer
_tracer: Optional[Tracer] = None
_initialized: bool = False

logger = logging.getLogger("cross-tenant-bot.trace")


def configure_agent_framework_tracing(
    otlp_port: int = 4317,
    enable_sensitive_data: bool = True
) -> bool:
    """
    Configure Agent Framework tracing with AI Toolkit integration.
    
    Uses the built-in Agent Framework observability which automatically
    instruments chat clients, agents, and workflow operations.
    
    IMPORTANT: Before running, start trace collector via VS Code Command:
    ai-mlstudio.tracing.open
    
    Args:
        otlp_port: OTLP gRPC port (AI Toolkit default: 4317)
        enable_sensitive_data: Capture prompts and completions (default: True)
    
    Returns:
        True if successfully configured, False otherwise.
    """
    global _tracer, _initialized
    
    if _initialized:
        return True
    
    try:
        from agent_framework.observability import configure_otel_providers
        
        configure_otel_providers(
            vs_code_extension_port=otlp_port,
            enable_sensitive_data=enable_sensitive_data
        )
        
        _tracer = trace.get_tracer(__name__)
        _initialized = True
        
        logger.info(f"Agent Framework tracing configured (OTLP port: {otlp_port})")
        return True
        
    except ImportError:
        logger.warning("agent_framework.observability not available - tracing disabled")
        return False
    except Exception as e:
        logger.error(f"Failed to configure Agent Framework tracing: {e}")
        return False


def configure_azure_monitor_telemetry() -> bool:
    """
    Configure Azure Monitor OpenTelemetry for distributed tracing and logging.
    
    Returns:
        True if successfully configured, False otherwise.
    """
    global _tracer, _initialized
    
    if _initialized:
        return True
    
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    
    if not connection_string:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING not set. "
            "Telemetry will not be sent to Azure Monitor."
        )
        return False
    
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        
        # Configure Azure Monitor with OpenTelemetry
        # This automatically instruments logging, traces, and metrics
        configure_azure_monitor(
            connection_string=connection_string,
            logger_name="cross-tenant-bot",  # Root logger namespace for the app
        )
        
        _tracer = trace.get_tracer(__name__)
        _initialized = True
        
        logger.info("Azure Monitor OpenTelemetry configured successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to configure Azure Monitor: {e}")
        return False


def configure_telemetry() -> bool:
    """
    Configure telemetry based on environment.
    
    - If LOCAL_DEBUG=true and AI Toolkit is available, uses Agent Framework tracing
    - Otherwise, uses Azure Monitor if APPLICATIONINSIGHTS_CONNECTION_STRING is set
    
    Returns:
        True if any telemetry provider was configured.
    """
    local_debug = os.getenv("LOCAL_DEBUG", "").lower() in ("true", "1", "yes")
    
    if local_debug:
        # Try Agent Framework tracing first for local development
        if configure_agent_framework_tracing():
            return True
    
    # Fall back to Azure Monitor for production
    return configure_azure_monitor_telemetry()


def get_tracer() -> Optional[Tracer]:
    """
    Get the OpenTelemetry tracer instance.
    
    Returns:
        The tracer if initialized, None otherwise.
    """
    return _tracer


def is_telemetry_enabled() -> bool:
    """
    Check if Azure Monitor telemetry is enabled.
    
    Returns:
        True if telemetry is configured and enabled.
    """
    return _initialized
