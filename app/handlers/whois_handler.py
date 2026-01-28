# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Whois Handler - Look up user information via RSC.
"""

import logging
from typing import Optional

from microsoft_agents.hosting.core import TurnContext, TurnState

from app.handlers.base import CommandHandler
from app.handlers.registry import handler_registry
from app.config.settings import settings
from app.core.utilities.rsc import get_user_by_id, is_rsc_enabled

logger = logging.getLogger(__name__)


class WhoisHandler(CommandHandler):
    """Handler for /whois command."""
    
    @property
    def command(self) -> str:
        return "whois"
    
    @property
    def description(self) -> str:
        return "Look up a user by ID"
    
    @property
    def category(self) -> str:
        return "RSC"
    
    @property
    def is_enabled(self) -> bool:
        """Only enabled if RSC is configured."""
        return settings.ENABLE_RSC
    
    async def handle(
        self,
        context: TurnContext,
        state: TurnState,
        args: str
    ) -> Optional[str]:
        """Look up user information."""
        
        if not args.strip():
            return "Usage: `/whois [user-aad-object-id]`"
        
        user_id = args.strip()
        user_context = self.get_user_context(context)
        tenant_id = user_context.user_tenant_id or settings.AZURE_TENANT_ID
        
        if not is_rsc_enabled():
            return "⚠️ RSC is not enabled. User lookup requires RSC permissions."
        
        try:
            user_info = await get_user_by_id(user_id, tenant_id)
            
            if user_info:
                display_name = user_info.get("displayName", "Unknown")
                job_title = user_info.get("jobTitle", "Not specified")
                email = user_info.get("mail", user_info.get("userPrincipalName", "Not specified"))
                department = user_info.get("department", "Not specified")
                
                return f"""
**👤 User Information:**

• **Name:** {display_name}
• **Job Title:** {job_title}
• **Email:** {email}
• **Department:** {department}

_Retrieved using application permissions (RSC)_
""".strip()
            else:
                return f"Could not find user with ID: {user_id}"
                
        except Exception as e:
            logger.error(f"Error looking up user: {e}", exc_info=True)
            return f"❌ Error looking up user: {str(e)}"


# Register the handler
handler_registry.register(WhoisHandler())
