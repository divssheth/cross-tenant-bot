# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
AI Handlers - AI-powered commands using the configured agent.

These handlers use the agent from app.agents to generate responses.
To change AI behavior, modify the agent implementation or prompts.
"""

import logging
from typing import Optional

from microsoft_agents.hosting.core import TurnContext, TurnState

from app.handlers.base import CommandHandler
from app.handlers.registry import handler_registry
from app.core import get_conversation_type_from_activity
from app.core.utilities.teams_helpers import get_conversation_context
from app.agents import get_agent

logger = logging.getLogger(__name__)


class AskHandler(CommandHandler):
    """Handler for /ask command - AI question answering."""
    
    @property
    def command(self) -> str:
        return "ask"
    
    @property
    def description(self) -> str:
        return "Ask AI a question about conversation"
    
    @property
    def category(self) -> str:
        return "AI"
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Handle /ask command."""
        
        question = args.strip()
        
        if not question:
            return "Usage: `/ask [your question]`\n\nExample: `/ask What was discussed about the project deadline?`"
        
        agent = get_agent()
        if not agent.is_available:
            return "⚠️ AI features are not configured. Please set AZURE_AI_PROJECT_ENDPOINT."
        
        # Get conversation context
        messages = await get_conversation_context(context, max_messages=30)
        
        if not messages:
            return "No conversation history available to answer questions about."
        
        # Use agent to answer
        response = await agent.answer_question(question, messages)
        return f"🤖 **AI Answer:**\n\n{response}"


class SummarizeHandler(CommandHandler):
    """Handler for /summarize command - AI conversation summary."""
    
    @property
    def command(self) -> str:
        return "summarize"
    
    @property
    def description(self) -> str:
        return "Get AI summary of conversation"
    
    @property
    def category(self) -> str:
        return "AI"
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Handle /summarize command."""
        
        agent = get_agent()
        if not agent.is_available:
            return "⚠️ AI features are not configured. Please set AZURE_AI_PROJECT_ENDPOINT."
        
        # Get conversation context
        messages = await get_conversation_context(context, max_messages=50)
        
        if not messages:
            return "No conversation history available to summarize."
        
        # Optional focus from args
        focus = args.strip() if args.strip() else None
        
        # Use agent to summarize
        summary = await agent.summarize(messages, focus)
        return f"📝 **Conversation Summary:**\n\n{summary}"


class DefaultMessageHandler(CommandHandler):
    """
    Default handler for non-command messages.
    
    This handler is used when a message doesn't start with a command.
    It uses the AI agent to generate contextual responses.
    """
    
    @property
    def command(self) -> str:
        return "__default__"  # Special marker - not a real command
    
    @property
    def description(self) -> str:
        return "AI-powered chat responses"
    
    @property
    def category(self) -> str:
        return "AI"
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Handle non-command messages with AI."""
        
        message = args  # For default handler, args is the full message
        user_context = self.get_user_context(context)
        
        agent = get_agent()
        
        # If AI is available, use it for intelligent responses
        if agent.is_available:
            # Get conversation context
            messages = await get_conversation_context(context, max_messages=20)
            conv_type = get_conversation_type_from_activity(context.activity)
            
            # Format context
            context_str = agent._format_messages_for_context(messages) if messages else ""
            
            # Generate AI response
            response = await agent.process(
                user_message=message,
                context=context_str,
                history=messages,
                conversation_type=conv_type
            )
            
            if user_context.is_cross_tenant() and user_context.user_tenant_id:
                response += f"\n\n_Cross-tenant message from {user_context.user_tenant_id[:20]}..._"
            
            return response
        
        # Fallback to simple echo if AI not available
        response = f"You said: **{message}**"
        
        if user_context.is_cross_tenant() and user_context.user_tenant_id:
            response += (
                f"\n\n_This is a cross-tenant message. "
                f"You are from {user_context.user_tenant_id[:20]}..._"
            )
        
        response += "\n\n💡 _Tip: Configure AZURE_AI_PROJECT_ENDPOINT to enable AI-powered responses._"
        
        return response


# Register handlers
handler_registry.register(AskHandler())
handler_registry.register(SummarizeHandler())
handler_registry.register_default(DefaultMessageHandler())
