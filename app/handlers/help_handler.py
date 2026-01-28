# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Help Handler - Shows available commands.
"""

from typing import Optional

from microsoft_agents.hosting.core import TurnContext, TurnState

from app.handlers.base import CommandHandler
from app.handlers.registry import handler_registry
from app.config.settings import settings
from app.agents import get_agent


class HelpHandler(CommandHandler):
    """Handler for /help command."""
    
    @property
    def command(self) -> str:
        return "help"
    
    @property
    def description(self) -> str:
        return "Show available commands"
    
    @property
    def category(self) -> str:
        return "Basic"
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Generate help text from registered handlers."""
        
        # Get status of features
        agent = get_agent()
        ai_status = "✅ Enabled" if agent.is_available else "❌ Not configured"
        rsc_status = "✅ Enabled" if settings.ENABLE_RSC else "❌ Disabled"
        
        # Group handlers by category
        categories = handler_registry.get_handlers_by_category()
        
        help_sections = []
        
        # Define category order and emoji
        category_config = {
            "Basic": "📋",
            "Context": "📚",
            "AI": "🤖",
            "RSC": "🔐",
        }
        
        # Build help text for each category
        for category, emoji in category_config.items():
            if category in categories:
                handlers = categories[category]
                commands = [f"• `/{h.command}` - {h.description}" for h in handlers]
                help_sections.append(f"{emoji} **{category} Commands:**\n" + "\n".join(commands))
        
        # Add any remaining categories
        for category, handlers in categories.items():
            if category not in category_config:
                commands = [f"• `/{h.command}` - {h.description}" for h in handlers]
                help_sections.append(f"**{category} Commands:**\n" + "\n".join(commands))
        
        # Build final help text
        help_text = """**Available Commands:**

""" + "\n\n".join(help_sections) + f"""

💬 **AI Chat:** Simply type any message (without a command) and the AI will respond using conversation context.

**Status:**
• AI: {ai_status}
• RSC: {rsc_status}
"""
        
        return help_text.strip()


# Register the handler
handler_registry.register(HelpHandler())
