# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Handler Registry - Auto-discovers and manages command handlers.

Handlers are automatically discovered when imported.
The registry provides routing from commands to handlers.
"""

import logging
from typing import Dict, List, Optional, Type

from microsoft_agents.hosting.core import TurnContext, TurnState

from app.handlers.base import CommandHandler

logger = logging.getLogger(__name__)


class HandlerRegistry:
    """
    Registry for command handlers.
    
    Manages handler registration and routing.
    Handlers register themselves when instantiated.
    """
    
    def __init__(self):
        """Initialize the handler registry."""
        self._handlers: Dict[str, CommandHandler] = {}
        self._default_handler: Optional[CommandHandler] = None
    
    def register(self, handler: CommandHandler):
        """
        Register a command handler.
        
        Args:
            handler: The handler instance to register
        """
        command = handler.command.lower()
        
        if command in self._handlers:
            logger.warning(f"Handler for /{command} already registered, overwriting")
        
        self._handlers[command] = handler
        logger.debug(f"Registered handler for /{command}")
    
    def register_default(self, handler: CommandHandler):
        """
        Register a default handler for non-command messages.
        
        Args:
            handler: The handler to use for non-command messages
        """
        self._default_handler = handler
        logger.debug("Registered default message handler")
    
    def get_handler(self, command: str) -> Optional[CommandHandler]:
        """
        Get a handler by command name.
        
        Args:
            command: The command (without slash)
            
        Returns:
            Handler instance or None
        """
        handler = self._handlers.get(command.lower())
        
        if handler and not handler.is_enabled:
            return None
        
        return handler
    
    def get_default_handler(self) -> Optional[CommandHandler]:
        """Get the default message handler."""
        return self._default_handler
    
    def get_all_handlers(self) -> List[CommandHandler]:
        """
        Get all registered handlers.
        
        Returns:
            List of all handler instances
        """
        return [h for h in self._handlers.values() if h.is_enabled]
    
    def get_handlers_by_category(self) -> Dict[str, List[CommandHandler]]:
        """
        Get handlers grouped by category.
        
        Returns:
            Dict mapping category names to handler lists
        """
        categories: Dict[str, List[CommandHandler]] = {}
        
        for handler in self.get_all_handlers():
            category = handler.category
            if category not in categories:
                categories[category] = []
            categories[category].append(handler)
        
        return categories
    
    async def route(
        self,
        context: TurnContext,
        state: TurnState,
        message: str
    ) -> Optional[str]:
        """
        Route a message to the appropriate handler.
        
        Args:
            context: The TurnContext
            state: The TurnState
            message: The user's message text
            
        Returns:
            Response string or None
        """
        message_lower = message.lower().strip()
        
        # Check if it's a command
        if message_lower.startswith("/"):
            parts = message_lower[1:].split(maxsplit=1)
            command = parts[0]
            args = message[len(command) + 2:].strip() if len(parts) > 1 else ""
            
            handler = self.get_handler(command)
            if handler:
                logger.debug(f"Routing /{command} to {handler.__class__.__name__}")
                return await handler.handle(context, state, args)
            else:
                return f"Unknown command: /{command}\n\nType `/help` for available commands."
        
        # Not a command - use default handler
        if self._default_handler:
            return await self._default_handler.handle(context, state, message)
        
        return None


# Global registry instance
handler_registry = HandlerRegistry()


def register_handler(handler_class: Type[CommandHandler]) -> Type[CommandHandler]:
    """
    Decorator to auto-register a handler class.
    
    Usage:
        @register_handler
        class MyHandler(CommandHandler):
            ...
    
    Args:
        handler_class: The handler class to register
        
    Returns:
        The handler class (unchanged)
    """
    instance = handler_class()
    handler_registry.register(instance)
    return handler_class
