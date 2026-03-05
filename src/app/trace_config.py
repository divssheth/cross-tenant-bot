"""
Trace configuration for request tracking with Azure Monitor OpenTelemetry.
"""
import os
import logging
import contextvars
from typing import Optional

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry.trace import Tracer

# Context variables for distributed tracing
trace_id: contextvars.ContextVar[str] = contextvars.ContextVar('trace_id', default='')
traceparent: contextvars.ContextVar[str] = contextvars.ContextVar('traceparent', default='')

# Module-level tracer
_tracer: Optional[Tracer] = None
_initialized: bool = False

logger = logging.getLogger("cross-tenant-bot.trace")


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
