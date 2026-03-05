"""
Logging configuration for the bot application with Azure Monitor integration.
"""
import logging
import sys
from typing import Optional


def configure_logging(level: int = logging.INFO, logger_name: str = "cross-tenant-bot") -> logging.Logger:
    """
    Configure application logging.
    
    When Azure Monitor OpenTelemetry is configured (via trace_config),
    logs will automatically be sent to Application Insights.
    
    Args:
        level: The logging level (default: INFO)
        logger_name: The logger namespace (default: cross-tenant-bot)
        
    Returns:
        The configured logger instance.
    """
    # Configure root logging format
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Get the application logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    # Reduce noise from libraries
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.monitor").setLevel(logging.WARNING)
    logging.getLogger("msal").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry").setLevel(logging.WARNING)
    
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance under the cross-tenant-bot namespace.
    
    Args:
        name: Optional sub-namespace (e.g., 'handlers' -> 'cross-tenant-bot.handlers')
        
    Returns:
        A logger instance.
    """
    if name:
        return logging.getLogger(f"cross-tenant-bot.{name}")
    return logging.getLogger("cross-tenant-bot")
