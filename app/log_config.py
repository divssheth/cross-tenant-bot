"""
Logging configuration for the bot application.
"""
import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    """Configure application logging."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Reduce noise from libraries
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("msal").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
