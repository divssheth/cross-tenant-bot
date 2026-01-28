# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Info Handler - Shows user and tenant information.
"""

from typing import Optional

from microsoft_agents.hosting.core import TurnContext, TurnState

from app.handlers.base import CommandHandler
from app.handlers.registry import handler_registry


class InfoHandler(CommandHandler):
    """Handler for /info command."""
    
    @property
    def command(self) -> str:
        return "info"
    
    @property
    def description(self) -> str:
        return "Show user and tenant information"
    
    @property
    def category(self) -> str:
        return "Basic"
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Show user context information."""
        
        user_context = self.get_user_context(context)
        ctx = user_context.to_dict()
        
        cross_tenant_status = (
            "Yes - Cross-tenant communication"
            if ctx['is_cross_tenant']
            else "No - Same tenant"
        )
        
        info_text = f"""
**User Information:**

• **Name:** {ctx['user_name']}
• **User ID:** {ctx['user_id']}
• **User Tenant:** {ctx['user_tenant']}
• **Bot Tenant:** {ctx['bot_tenant']}
• **Cross-Tenant:** {cross_tenant_status}
• **Conversation ID:** {ctx['conversation_id']}
• **Message Time:** {ctx['timestamp']}
"""
        return info_text.strip()


# Register the handler
handler_registry.register(InfoHandler())
