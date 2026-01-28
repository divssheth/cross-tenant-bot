# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Status Handler - Shows bot status and configuration.
"""

from typing import Optional

from microsoft_agents.hosting.core import TurnContext, TurnState

from app.handlers.base import CommandHandler
from app.handlers.registry import handler_registry
from app.config.settings import settings
from app.core import conversation_manager
from app.agents import get_agent


class StatusHandler(CommandHandler):
    """Handler for /status command."""
    
    @property
    def command(self) -> str:
        return "status"
    
    @property
    def description(self) -> str:
        return "Show bot status and configuration"
    
    @property
    def category(self) -> str:
        return "Basic"
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Show bot status."""
        
        user_context = self.get_user_context(context)
        
        tenant_id = settings.AZURE_TENANT_ID
        tenant_display = tenant_id[:20] + "..." if len(tenant_id) > 20 else tenant_id
        
        # Get conversation stats
        conv_stats = conversation_manager.get_stats()
        
        # Get feature status
        agent = get_agent()
        ai_status = "✅ Enabled" if agent.is_available else "❌ Not configured"
        rsc_status = "✅ Enabled" if settings.ENABLE_RSC else "❌ Disabled"
        
        status_text = f"""
**Bot Status:**

• **Status:** Online and responding ✅
• **Bot Tenant ID:** {tenant_display}
• **Authentication:** User-Assigned Managed Identity (UAMI)

**Features:**
• **AI Integration:** {ai_status}
• **RSC (Channel Context):** {rsc_status}

**Conversation State:**
• **Total Conversations:** {conv_stats['total_conversations']}
• **Personal Chats:** {conv_stats['personal_chats']}
• **Group Chats:** {conv_stats['group_chats']}
• **Channels:** {conv_stats['channels']}
• **Messages Stored:** {conv_stats['total_messages_stored']}
"""
        
        # Add RSC configuration details if enabled
        if settings.ENABLE_RSC:
            graph_app_id = settings.GRAPH_APP_ID
            graph_app_display = graph_app_id[:20] + "..." if len(graph_app_id) > 20 else graph_app_id
            key_vault = settings.KEY_VAULT_NAME or "Not set"
            
            status_text += f"""
**RSC Configuration:**
• **Graph App ID:** {graph_app_display}
• **Key Vault:** {key_vault}
• **User Tenant:** {user_context.user_tenant_id or 'Same as bot'}
"""
        
        return status_text.strip()


# Register the handler
handler_registry.register(StatusHandler())
