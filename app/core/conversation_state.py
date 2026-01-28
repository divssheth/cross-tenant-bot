# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Conversation State Manager

This module manages conversation history for 1:1 chats, group chats, and channels.
For 1:1 and group chats, messages are stored in-memory as the bot receives them.
For channels, historical messages are retrieved from Graph API using RSC.

No user authentication is required - this uses in-memory state and application
permissions for Graph API.

This is part of the core infrastructure and should not need modification.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field
from collections import deque

from app.config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ConversationMessage:
    """Represents a single message in a conversation."""
    
    sender_id: str
    sender_name: str
    text: str
    timestamp: datetime
    message_id: str = ""
    is_from_bot: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
            "message_id": self.message_id,
            "is_from_bot": self.is_from_bot
        }
    
    def __str__(self) -> str:
        """Format as readable string."""
        prefix = "🤖" if self.is_from_bot else "👤"
        return f"{prefix} **{self.sender_name}**: {self.text}"


@dataclass
class ConversationState:
    """Tracks state for a single conversation."""
    
    conversation_id: str
    conversation_type: str  # "personal", "groupChat", "channel"
    team_id: Optional[str] = None
    channel_id: Optional[str] = None
    tenant_id: Optional[str] = None
    messages: deque = field(default_factory=lambda: deque(maxlen=settings.MAX_CONTEXT_MESSAGES))
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    
    def add_message(self, message: ConversationMessage):
        """Add a message to the conversation history."""
        self.messages.append(message)
        self.last_activity = datetime.now()
        logger.debug(f"Added message to {self.conversation_type} conversation {self.conversation_id[:8]}...")
    
    def get_messages(self, limit: Optional[int] = None) -> List[ConversationMessage]:
        """Get messages from the conversation history."""
        messages = list(self.messages)
        if limit:
            return messages[-limit:]
        return messages
    
    def get_context_string(self, limit: int = 10) -> str:
        """Get formatted context string for AI/display."""
        messages = self.get_messages(limit)
        if not messages:
            return "No conversation history available."
        
        lines = [str(msg) for msg in messages]
        return "\n".join(lines)
    
    def clear(self):
        """Clear all messages from the conversation."""
        self.messages.clear()


class ConversationStateManager:
    """
    Manages conversation state across all conversations.
    
    Provides:
    - In-memory storage for 1:1 and group chat messages
    - Automatic message tracking as bot receives them
    - Integration with Graph API for channel history (RSC)
    """
    
    def __init__(self):
        """Initialize the conversation state manager."""
        self._conversations: Dict[str, ConversationState] = {}
        logger.info(f"ConversationStateManager initialized (max {settings.MAX_CONTEXT_MESSAGES} messages per conversation)")
    
    def get_or_create_conversation(
        self,
        conversation_id: str,
        conversation_type: str,
        team_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> ConversationState:
        """
        Get existing conversation state or create new one.
        
        Args:
            conversation_id: The conversation ID from Teams
            conversation_type: "personal", "groupChat", or "channel"
            team_id: Team ID (for channel conversations)
            channel_id: Channel ID (for channel conversations)
            tenant_id: Tenant ID for cross-tenant tracking
            
        Returns:
            ConversationState object
        """
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = ConversationState(
                conversation_id=conversation_id,
                conversation_type=conversation_type,
                team_id=team_id,
                channel_id=channel_id,
                tenant_id=tenant_id
            )
            logger.info(f"Created new conversation state for {conversation_type}: {conversation_id[:20]}...")
        
        return self._conversations[conversation_id]
    
    def add_user_message(
        self,
        conversation_id: str,
        sender_id: str,
        sender_name: str,
        text: str,
        message_id: str = "",
        conversation_type: str = "personal",
        team_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ):
        """
        Add a user message to the conversation history.
        
        Call this when the bot receives a message from a user.
        """
        conversation = self.get_or_create_conversation(
            conversation_id, conversation_type, team_id, channel_id, tenant_id
        )
        
        message = ConversationMessage(
            sender_id=sender_id,
            sender_name=sender_name,
            text=text,
            timestamp=datetime.now(),
            message_id=message_id,
            is_from_bot=False
        )
        
        conversation.add_message(message)
    
    def add_bot_message(
        self,
        conversation_id: str,
        text: str,
        message_id: str = ""
    ):
        """
        Add a bot message to the conversation history.
        
        Call this when the bot sends a message.
        """
        if conversation_id not in self._conversations:
            logger.warning(f"Conversation {conversation_id[:20]}... not found for bot message")
            return
        
        conversation = self._conversations[conversation_id]
        
        message = ConversationMessage(
            sender_id="bot",
            sender_name="Bot",
            text=text,
            timestamp=datetime.now(),
            message_id=message_id,
            is_from_bot=True
        )
        
        conversation.add_message(message)
    
    def get_context(
        self,
        conversation_id: str,
        limit: int = 10
    ) -> str:
        """
        Get the conversation context as a formatted string.
        
        Args:
            conversation_id: The conversation ID
            limit: Maximum number of messages to include
            
        Returns:
            Formatted string of recent messages
        """
        if conversation_id not in self._conversations:
            return "No conversation history available."
        
        return self._conversations[conversation_id].get_context_string(limit)
    
    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        """Get a conversation by ID."""
        return self._conversations.get(conversation_id)
    
    def get_conversation_info(self, conversation_id: str) -> Dict[str, Any]:
        """Get information about a conversation."""
        if conversation_id not in self._conversations:
            return {"exists": False}
        
        conv = self._conversations[conversation_id]
        return {
            "exists": True,
            "type": conv.conversation_type,
            "message_count": len(conv.messages),
            "team_id": conv.team_id,
            "channel_id": conv.channel_id,
            "tenant_id": conv.tenant_id,
            "created_at": conv.created_at.isoformat(),
            "last_activity": conv.last_activity.isoformat()
        }
    
    def clear_conversation(self, conversation_id: str):
        """Clear a conversation's history."""
        if conversation_id in self._conversations:
            self._conversations[conversation_id].clear()
            logger.info(f"Cleared conversation {conversation_id[:20]}...")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about all conversations."""
        personal = sum(1 for c in self._conversations.values() if c.conversation_type == "personal")
        group = sum(1 for c in self._conversations.values() if c.conversation_type == "groupChat")
        channel = sum(1 for c in self._conversations.values() if c.conversation_type == "channel")
        total_messages = sum(len(c.messages) for c in self._conversations.values())
        
        return {
            "total_conversations": len(self._conversations),
            "personal_chats": personal,
            "group_chats": group,
            "channels": channel,
            "total_messages_stored": total_messages,
            "max_messages_per_conversation": settings.MAX_CONTEXT_MESSAGES
        }


# Global instance
conversation_manager = ConversationStateManager()


def get_conversation_type_from_activity(activity) -> str:
    """
    Determine the conversation type from a Teams activity.
    
    Args:
        activity: The incoming activity object
        
    Returns:
        "personal", "groupChat", or "channel"
    """
    if hasattr(activity, 'conversation') and activity.conversation:
        conv_type = getattr(activity.conversation, 'conversation_type', None)
        
        if conv_type:
            return conv_type
        
        # Fallback: check channel_data
        if hasattr(activity, 'channel_data') and activity.channel_data:
            channel_data = activity.channel_data
            if isinstance(channel_data, dict):
                if channel_data.get('channel'):
                    return "channel"
                if channel_data.get('team'):
                    return "channel"
    
    # Default to personal
    return "personal"


def extract_team_channel_ids(activity) -> tuple:
    """
    Extract team and channel IDs from a Teams activity.
    
    Args:
        activity: The incoming activity object
        
    Returns:
        Tuple of (team_id, channel_id), either may be None
    """
    team_id = None
    channel_id = None
    
    if hasattr(activity, 'channel_data') and activity.channel_data:
        channel_data = activity.channel_data
        if isinstance(channel_data, dict):
            team_data = channel_data.get('team', {})
            channel_data_inner = channel_data.get('channel', {})
            
            if isinstance(team_data, dict):
                team_id = team_data.get('id')
            
            if isinstance(channel_data_inner, dict):
                channel_id = channel_data_inner.get('id')
    
    return team_id, channel_id
