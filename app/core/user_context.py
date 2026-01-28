# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
User Context - Encapsulates user information from Teams activity.

This is part of the core infrastructure and should not need modification.
"""

import os
import logging
from datetime import datetime
from typing import Optional, Dict

from microsoft_agents.hosting.core import TurnContext

logger = logging.getLogger(__name__)


class UserContext:
    """
    Encapsulates information about a user sending a message.

    Tracks user details, tenant information, and conversation context.
    """

    def __init__(self, turn_context: TurnContext):
        """Initialize user context from the Teams activity."""
        self.user_id: str = turn_context.activity.from_property.id if turn_context.activity.from_property else "unknown"
        self.user_name: str = (turn_context.activity.from_property.name if turn_context.activity.from_property and turn_context.activity.from_property.name else None) or "User"
        self.conversation_id: str = turn_context.activity.conversation.id if turn_context.activity.conversation else "unknown"
        self.activity_id: str = turn_context.activity.id or "unknown"
        self.timestamp: str = datetime.now().isoformat()

        # Extract user's home tenant
        self.user_tenant_id: Optional[str] = self._extract_tenant_id(turn_context)

        # Bot's tenant (from configuration)
        self.bot_tenant_id: str = os.getenv("AZURE_TENANT_ID", "unknown")

    def _extract_tenant_id(self, turn_context: TurnContext) -> Optional[str]:
        """
        Extract the user's home tenant ID from the Teams activity.

        Teams includes tenant information in the channel_data field
        of the activity when a cross-tenant user communicates with the bot.
        """
        try:
            if hasattr(turn_context.activity, 'channel_data'):
                channel_data = turn_context.activity.channel_data
                if isinstance(channel_data, dict):
                    tenant_data = channel_data.get('tenant', {})
                    if isinstance(tenant_data, dict):
                        tenant_id = tenant_data.get('id')
                        if tenant_id:
                            return tenant_id
        except Exception as e:
            logger.debug(f"Could not extract tenant ID: {e}")

        return None

    def is_cross_tenant(self) -> bool:
        """Check if this is a cross-tenant communication."""
        return (
                self.user_tenant_id is not None and
                self.user_tenant_id != self.bot_tenant_id
        )

    def to_dict(self) -> Dict:
        """Convert user context to dictionary for logging."""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "user_tenant": self.user_tenant_id or "unknown",
            "bot_tenant": self.bot_tenant_id,
            "is_cross_tenant": self.is_cross_tenant(),
            "conversation_id": self.conversation_id,
            "timestamp": self.timestamp
        }
