# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Echo Handler - Simple echo command.
"""

from typing import Optional

from microsoft_agents.hosting.core import TurnContext, TurnState

from app.handlers.base import CommandHandler
from app.handlers.registry import handler_registry


class EchoHandler(CommandHandler):
    """Handler for /echo command."""
    
    @property
    def command(self) -> str:
        return "echo"
    
    @property
    def description(self) -> str:
        return "Echo back your message"
    
    @property
    def category(self) -> str:
        return "Basic"
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Echo back the message."""
        
        if not args.strip():
            return "Please provide text to echo. Usage: `/echo [text]`"
        
        user_context = self.get_user_context(context)
        
        response = f"🔊 **Echo:** {args}"
        
        if user_context.is_cross_tenant() and user_context.user_tenant_id:
            response += f"\n\n_(Cross-tenant message from {user_context.user_tenant_id[:20]}...)_"
        
        return response


# Register the handler
handler_registry.register(EchoHandler())
