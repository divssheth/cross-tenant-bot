# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Base Command Handler - Abstract interface for command handlers.

Extend this class to create your own command handlers.
Handlers are auto-discovered and registered by the HandlerRegistry.
"""

from abc import ABC, abstractmethod
from typing import Optional
import logging

from microsoft_agents.hosting.core import TurnContext, TurnState

from app.core.user_context import UserContext

logger = logging.getLogger(__name__)


class CommandHandler(ABC):
    """
    Abstract base class for command handlers.
    
    Extend this class to create handlers for specific commands.
    The handler will be automatically discovered and registered.
    
    Example:
        class MyHandler(CommandHandler):
            @property
            def command(self) -> str:
                return "mycommand"  # Responds to /mycommand
            
            @property
            def description(self) -> str:
                return "Description shown in /help"
            
            async def handle(self, context, state, args):
                await context.send_activity("Response!")
    """
    
    @property
    @abstractmethod
    def command(self) -> str:
        """
        The command trigger (without the leading slash).
        
        Example: "help" for /help command
        
        Returns:
            Command string (lowercase, no slash)
        """
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """
        Description of what the command does.
        
        This is shown in the /help output.
        
        Returns:
            Human-readable description
        """
        pass
    
    @property
    def category(self) -> str:
        """
        Category for grouping in help output.
        
        Override to customize the category.
        Default: "General"
        
        Returns:
            Category name
        """
        return "General"
    
    @property
    def is_enabled(self) -> bool:
        """
        Whether the handler is currently enabled.
        
        Override to add conditional logic (e.g., feature flags).
        Default: True
        
        Returns:
            True if the handler should be active
        """
        return True
    
    @abstractmethod
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """
        Handle the command.
        
        Implement your command logic here. You can either:
        1. Return a string response (will be sent automatically)
        2. Call context.send_activity() directly and return None
        
        Args:
            context: The TurnContext from the bot
            state: The TurnState for conversation state
            args: Arguments passed after the command (e.g., "/ask hello" -> "hello")
            
        Returns:
            Response string to send, or None if already sent
        """
        pass
    
    def get_user_context(self, context: TurnContext) -> UserContext:
        """
        Helper: Get UserContext from TurnContext.
        
        Args:
            context: The TurnContext
            
        Returns:
            UserContext object with user details
        """
        return UserContext(context)
