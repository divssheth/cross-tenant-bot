# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Context Handlers - Shows conversation context.
"""

from typing import Optional

from microsoft_agents.hosting.core import TurnContext, TurnState

from app.handlers.base import CommandHandler
from app.handlers.registry import handler_registry
from app.config.settings import settings
from app.config.prompts import RSC_DISABLED_MESSAGE
from app.core import (
    conversation_manager,
    get_conversation_type_from_activity,
    extract_team_channel_ids,
)
from app.core.utilities.rsc import (
    is_rsc_enabled,
    get_channel_messages_with_replies,
    format_messages_for_context,
)


class ContextHandler(CommandHandler):
    """Handler for /context command."""
    
    @property
    def command(self) -> str:
        return "context"
    
    @property
    def description(self) -> str:
        return "Show recent conversation context"
    
    @property
    def category(self) -> str:
        return "Context"
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Show conversation context."""
        
        user_context = self.get_user_context(context)
        conversation_id = context.activity.conversation.id if context.activity.conversation else None
        
        if not conversation_id:
            return "❌ Could not determine conversation ID."
        
        # Get conversation type
        conv_type = get_conversation_type_from_activity(context.activity)
        team_id, channel_id = extract_team_channel_ids(context.activity)
        
        # Get tenant ID for cross-tenant scenarios
        tenant_id = user_context.user_tenant_id or settings.AZURE_TENANT_ID
        
        if conv_type == "channel" and team_id and channel_id:
            # For channels, use RSC to get messages from Graph API (if enabled)
            if not is_rsc_enabled():
                return RSC_DISABLED_MESSAGE
            
            try:
                max_messages = settings.MAX_GRAPH_MESSAGES
                messages = await get_channel_messages_with_replies(
                    team_id=team_id,
                    channel_id=channel_id,
                    top=max_messages,
                    include_replies=True,
                    max_replies_per_message=10,
                    tenant_id=tenant_id
                )
                
                if messages:
                    context_str = format_messages_for_context(messages, max_messages=10, include_replies=True)
                    return f"""
**📚 Channel Context (from Graph API via RSC):**

{context_str}

_Retrieved {len(messages)} messages from channel history_
""".strip()
                else:
                    return "No channel messages found. Ensure RSC permissions are granted and the bot is installed in this team."
                    
            except Exception as e:
                return f"❌ Error retrieving channel context: {str(e)}"
        
        else:
            # For 1:1 and group chats, use in-memory conversation state
            conversation_context = conversation_manager.get_context(conversation_id, limit=10)
            
            if conversation_context == "No conversation history available.":
                return """
**📚 Conversation Context:**

No messages stored yet. Send some messages and then try `/context` again.

_Note: Context is stored in memory and resets when the bot restarts._
""".strip()
            
            return f"""
**📚 Conversation Context ({conv_type}):**

{conversation_context}

_Showing last 10 messages from this conversation_
""".strip()


class ContextInfoHandler(CommandHandler):
    """Handler for /contextinfo command."""
    
    @property
    def command(self) -> str:
        return "contextinfo"
    
    @property
    def description(self) -> str:
        return "Show conversation state information"
    
    @property
    def category(self) -> str:
        return "Context"
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Show conversation state info."""
        
        conversation_id = context.activity.conversation.id if context.activity.conversation else None
        
        if not conversation_id:
            return "❌ Could not determine conversation ID."
        
        info = conversation_manager.get_conversation_info(conversation_id)
        
        if not info.get("exists"):
            return "No conversation state exists for this chat yet."
        
        return f"""
**📊 Conversation State Info:**

• **Type:** {info.get('type', 'unknown')}
• **Messages Stored:** {info.get('message_count', 0)}
• **Team ID:** {info.get('team_id', 'N/A')[:20] + '...' if info.get('team_id') else 'N/A'}
• **Channel ID:** {info.get('channel_id', 'N/A')[:20] + '...' if info.get('channel_id') else 'N/A'}
• **Tenant ID:** {info.get('tenant_id', 'N/A')[:20] + '...' if info.get('tenant_id') else 'N/A'}
• **Created:** {info.get('created_at', 'N/A')}
• **Last Activity:** {info.get('last_activity', 'N/A')}
""".strip()


# Register handlers
handler_registry.register(ContextHandler())
handler_registry.register(ContextInfoHandler())
