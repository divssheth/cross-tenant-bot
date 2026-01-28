# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Teams Helpers - Utility functions for Teams-specific operations.

Use these helpers in your handlers to work with Teams context.
"""

import logging
from typing import List, Dict, Any, Optional

from microsoft_agents.hosting.core import TurnContext

from app.config.settings import settings
from app.core import (
    conversation_manager,
    get_conversation_type_from_activity,
    extract_team_channel_ids,
)
from app.core.user_context import UserContext

logger = logging.getLogger(__name__)


def is_channel_conversation(context: TurnContext) -> bool:
    """
    Check if the current conversation is in a Teams channel.
    
    Args:
        context: The TurnContext from the bot
        
    Returns:
        True if this is a channel conversation
    """
    conv_type = get_conversation_type_from_activity(context.activity)
    return conv_type == "channel"


def is_group_chat(context: TurnContext) -> bool:
    """
    Check if the current conversation is a group chat.
    
    Args:
        context: The TurnContext from the bot
        
    Returns:
        True if this is a group chat
    """
    conv_type = get_conversation_type_from_activity(context.activity)
    return conv_type == "groupChat"


def is_personal_chat(context: TurnContext) -> bool:
    """
    Check if the current conversation is a 1:1 personal chat.
    
    Args:
        context: The TurnContext from the bot
        
    Returns:
        True if this is a personal chat
    """
    conv_type = get_conversation_type_from_activity(context.activity)
    return conv_type == "personal"


async def get_conversation_context(
    context: TurnContext,
    max_messages: int = 20,
    include_replies: bool = True
) -> List[Dict[str, Any]]:
    """
    Get conversation context based on conversation type.
    
    For channels (with RSC enabled): Fetches from Graph API
    For 1:1 and group chats: Uses in-memory conversation state
    
    Args:
        context: The TurnContext from the bot
        max_messages: Maximum messages to return
        include_replies: Whether to include replies (for channels)
        
    Returns:
        List of message dictionaries
    """
    conversation_id = context.activity.conversation.id if context.activity.conversation else None
    if not conversation_id:
        return []
    
    conv_type = get_conversation_type_from_activity(context.activity)
    team_id, channel_id = extract_team_channel_ids(context.activity)
    user_context = UserContext(context)
    tenant_id = user_context.user_tenant_id or settings.AZURE_TENANT_ID
    
    messages = []
    
    # For channels, try RSC if enabled
    if conv_type == "channel" and team_id and channel_id and settings.ENABLE_RSC:
        from app.core.utilities.rsc import get_channel_messages_with_replies
        
        try:
            messages = await get_channel_messages_with_replies(
                team_id=team_id,
                channel_id=channel_id,
                top=max_messages,
                include_replies=include_replies,
                tenant_id=tenant_id
            )
        except Exception as e:
            logger.warning(f"Could not get channel messages via RSC: {e}")
    
    # Fallback to in-memory state
    if not messages:
        conv_state = conversation_manager.get_conversation(conversation_id)
        if conv_state:
            messages = [msg.to_dict() for msg in conv_state.get_messages(max_messages)]
    
    return messages


def track_user_message(
    context: TurnContext,
    user_context: UserContext,
    message_text: str
):
    """
    Track a user message in conversation state.
    
    Call this when processing incoming messages to maintain history.
    
    Args:
        context: The TurnContext from the bot
        user_context: The UserContext for the current user
        message_text: The text of the message
    """
    conversation_id = context.activity.conversation.id if context.activity.conversation else None
    if not conversation_id:
        return
    
    conv_type = get_conversation_type_from_activity(context.activity)
    team_id, channel_id = extract_team_channel_ids(context.activity)
    
    conversation_manager.add_user_message(
        conversation_id=conversation_id,
        sender_id=user_context.user_id,
        sender_name=user_context.user_name,
        text=message_text,
        message_id=context.activity.id or "",
        conversation_type=conv_type,
        team_id=team_id,
        channel_id=channel_id,
        tenant_id=user_context.user_tenant_id
    )


def track_bot_response(context: TurnContext, response_text: str):
    """
    Track a bot response in conversation state.
    
    Call this after sending a response to maintain history.
    
    Args:
        context: The TurnContext from the bot
        response_text: The text of the bot's response
    """
    conversation_id = context.activity.conversation.id if context.activity.conversation else None
    if not conversation_id:
        return
    
    # Truncate long responses for storage
    truncated = response_text[:200] + "..." if len(response_text) > 200 else response_text
    conversation_manager.add_bot_message(
        conversation_id=conversation_id,
        text=truncated
    )
