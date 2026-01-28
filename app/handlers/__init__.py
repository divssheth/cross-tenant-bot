# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Handlers Module - Command and Message Handlers

This module contains all the command handlers for the bot.
Handlers are auto-discovered and registered when the bot starts.

To add a new command:
1. Create a new file in this directory (e.g., my_handler.py)
2. Create a class extending CommandHandler
3. Implement the required methods
4. The handler will be auto-discovered and registered

Example:
    # handlers/my_handler.py
    from app.handlers.base import CommandHandler
    
    class MyCommandHandler(CommandHandler):
        @property
        def command(self) -> str:
            return "mycommand"
        
        @property
        def description(self) -> str:
            return "Does something cool"
        
        async def handle(self, context, state, args):
            await context.send_activity("Hello from my command!")

The handler will automatically respond to /mycommand
"""

from app.handlers.base import CommandHandler
from app.handlers.registry import HandlerRegistry, handler_registry

# Import all handlers to ensure they're registered
from app.handlers.help_handler import HelpHandler
from app.handlers.info_handler import InfoHandler
from app.handlers.status_handler import StatusHandler
from app.handlers.context_handler import ContextHandler, ContextInfoHandler
from app.handlers.ai_handler import AskHandler, SummarizeHandler
from app.handlers.echo_handler import EchoHandler
from app.handlers.whois_handler import WhoisHandler

__all__ = [
    "CommandHandler",
    "HandlerRegistry",
    "handler_registry",
    "HelpHandler",
    "InfoHandler",
    "StatusHandler",
    "ContextHandler",
    "ContextInfoHandler",
    "AskHandler",
    "SummarizeHandler",
    "EchoHandler",
    "WhoisHandler",
]
