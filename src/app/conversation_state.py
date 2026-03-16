# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Conversation State Manager

This module manages conversation history for 1:1 chats, group chats, and channels.
For 1:1 and group chats, messages are stored in-memory as the bot receives them.
For channels, historical messages are retrieved from Graph API using RSC.

No user authentication is required - this uses in-memory state and application
permissions for Graph API.
"""

import os
import re
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger("cross-tenant-bot.state")


# =============================================================================
# Team Mapping Cache
# =============================================================================

class TeamMappingCache:
    """
    Caches the mapping from Teams thread ID to AAD Group ID (M365 Group GUID).
    
    The aadGroupId is only available in conversationUpdate events when the bot
    is added to a team. Regular channel messages only contain the thread ID
    (e.g., 19:xxx@thread.tacv2), but Graph API requires the AAD Group ID (GUID).
    
    This cache stores the mapping when the bot is added to a team, so it can
    be looked up later when processing channel messages.
    
    Usage:
        # When bot is added to team (conversationUpdate):
        team_mapping_cache.add_mapping(thread_id, aad_group_id, tenant_id)
        
        # When processing channel message:
        aad_group_id = team_mapping_cache.get_aad_group_id(thread_id)
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._mappings: Dict[str, Dict[str, str]] = {}
            logger.info("TeamMappingCache initialized")
        return cls._instance
    
    def add_mapping(
        self, 
        thread_id: str, 
        aad_group_id: str, 
        tenant_id: Optional[str] = None,
        team_name: Optional[str] = None
    ) -> None:
        """
        Cache a mapping from thread ID to AAD Group ID.
        
        Args:
            thread_id: The Teams thread ID (e.g., 19:xxx@thread.tacv2)
            aad_group_id: The M365 Group ID (GUID format)
            tenant_id: Optional tenant ID for cross-tenant tracking
            team_name: Optional team name for logging
        """
        if not thread_id or not aad_group_id:
            logger.warning(f"Cannot cache mapping: thread_id={thread_id}, aad_group_id={aad_group_id}")
            return
        
        self._mappings[thread_id] = {
            "aad_group_id": aad_group_id,
            "tenant_id": tenant_id or "",
            "team_name": team_name or "",
            "cached_at": datetime.now().isoformat()
        }
        
        logger.info(
            f"✅ Cached team mapping: {thread_id[:30]}... → {aad_group_id} "
            f"(team: {team_name or 'unknown'})"
        )
    
    def get_aad_group_id(self, thread_id: str) -> Optional[str]:
        """
        Look up the AAD Group ID for a thread ID.
        
        Args:
            thread_id: The Teams thread ID to look up
            
        Returns:
            The AAD Group ID (GUID) if found, None otherwise
        """
        if not thread_id:
            return None
        
        mapping = self._mappings.get(thread_id)
        if mapping:
            aad_group_id = mapping.get("aad_group_id")
            logger.debug(f"Cache hit: {thread_id[:30]}... → {aad_group_id}")
            return aad_group_id
        
        logger.debug(f"Cache miss: {thread_id[:30]}...")
        return None
    
    def get_mapping_info(self, thread_id: str) -> Optional[Dict[str, str]]:
        """Get full mapping info including tenant and team name."""
        return self._mappings.get(thread_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "cached_teams": len(self._mappings),
            "mappings": {
                tid[:30] + "...": info.get("aad_group_id", "")[:20] + "..."
                for tid, info in self._mappings.items()
            }
        }
    
    def clear(self) -> None:
        """Clear all cached mappings."""
        self._mappings.clear()
        logger.info("TeamMappingCache cleared")


# Global instance
team_mapping_cache = TeamMappingCache()

# Maximum messages to store per conversation
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "20"))


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
    messages: deque = field(default_factory=lambda: deque(maxlen=MAX_CONTEXT_MESSAGES))
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
        logger.info(f"ConversationStateManager initialized (max {MAX_CONTEXT_MESSAGES} messages per conversation)")
    
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
            "max_messages_per_conversation": MAX_CONTEXT_MESSAGES
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


def extract_team_channel_ids(activity) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract team and channel IDs from a Teams activity.
    
    The team_id for Graph API must be the M365 Group ID (GUID format).
    
    Extraction priority:
    1. Try to get groupId from conversation.id (format: 19:xxx;groupId=GUID;tenantId=GUID)
    2. Try to get aadGroupId from channelData.team.aadGroupId (present in conversationUpdate)
    3. Fall back to cached mapping (thread_id → aadGroupId from when bot was added)
    
    Args:
        activity: The incoming activity object
        
    Returns:
        Tuple of (team_id, channel_id), either may be None.
        team_id will be the AAD Group ID (GUID) if available.
    """
    team_id = None
    channel_id = None
    thread_id = None  # The 19:xxx@thread.tacv2 format
    
    # Extract from conversation.id
    if hasattr(activity, 'conversation') and activity.conversation:
        conv_id = activity.conversation.id or ''
        
        # Extract groupId (M365 Group ID) - this is what we need for Graph API
        group_match = re.search(r'groupId=([a-f0-9-]+)', conv_id, re.IGNORECASE)
        if group_match:
            team_id = group_match.group(1)
            logger.debug(f"Found groupId in conversation.id: {team_id}")
        
        # Extract channel_id (the 19:xxx@thread.tacv2 part)
        channel_match = re.search(r'(19:[^;]+)', conv_id)
        if channel_match:
            channel_id = channel_match.group(1)
    
    # Get thread_id from channelData for cache lookup
    if hasattr(activity, 'channel_data') and activity.channel_data:
        channel_data = activity.channel_data
        if isinstance(channel_data, dict):
            # Get teamsTeamId or team.id as the thread ID
            thread_id = channel_data.get('teamsTeamId')
            
            team_data = channel_data.get('team', {})
            if isinstance(team_data, dict):
                if not thread_id:
                    thread_id = team_data.get('id')
                
                # Check if aadGroupId is directly available (conversationUpdate events)
                if not team_id:
                    aad_group_id = team_data.get('aadGroupId')
                    if aad_group_id:
                        team_id = aad_group_id
                        logger.debug(f"Found aadGroupId in channelData.team: {team_id}")
            
            # Fallback for channel_id
            if not channel_id:
                channel_data_inner = channel_data.get('channel', {})
                if isinstance(channel_data_inner, dict):
                    channel_id = channel_data_inner.get('id')
    
    # If we still don't have team_id, try the cache
    if not team_id and thread_id:
        cached_id = team_mapping_cache.get_aad_group_id(thread_id)
        if cached_id:
            team_id = cached_id
            logger.debug(f"Found aadGroupId in cache: {team_id}")
        else:
            logger.warning(
                f"Could not find AAD Group ID for team. Thread ID: {thread_id[:30]}... "
                f"The bot may need to be re-added to this team to cache the mapping."
            )
    
    return team_id, channel_id


def extract_team_info_for_caching(activity) -> Dict[str, Optional[str]]:
    """
    Extract team information from a conversationUpdate activity for caching.
    
    This should be called in on_members_added to capture the aadGroupId
    when the bot is added to a team.
    
    Args:
        activity: The incoming activity object
        
    Returns:
        Dict with thread_id, aad_group_id, tenant_id, team_name (any may be None)
    """
    result = {
        "thread_id": None,
        "aad_group_id": None,
        "tenant_id": None,
        "team_name": None,
        "event_type": None
    }
    
    if not hasattr(activity, 'channel_data') or not activity.channel_data:
        return result
    
    channel_data = activity.channel_data
    if not isinstance(channel_data, dict):
        return result
    
    # Log the full channel_data for debugging
    logger.info(f"📋 conversationUpdate channel_data: {json.dumps(channel_data, indent=2, default=str)}")
    
    result["event_type"] = channel_data.get("eventType")
    
    # Extract tenant ID
    tenant_data = channel_data.get("tenant", {})
    if isinstance(tenant_data, dict):
        result["tenant_id"] = tenant_data.get("id")
    
    # Extract team info
    team_data = channel_data.get("team", {})
    if isinstance(team_data, dict):
        result["thread_id"] = team_data.get("id")
        result["aad_group_id"] = team_data.get("aadGroupId")
        result["team_name"] = team_data.get("name")
        
        # Log what we found
        logger.info(
            f"📋 Team info extracted: "
            f"thread_id={result['thread_id'][:30] if result['thread_id'] else None}..., "
            f"aadGroupId={result['aad_group_id']}, "
            f"name={result['team_name']}, "
            f"eventType={result['event_type']}"
        )
    
    return result
