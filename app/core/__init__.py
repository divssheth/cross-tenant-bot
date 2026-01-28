# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Core module - Bot infrastructure (DO NOT MODIFY)

This module contains the stable bot infrastructure:
- Bot adapter and authentication
- Message routing
- Conversation state management
- Utility functions

These components should not need modification for typical customizations.
Instead, customize handlers/ and agents/ directories.
"""

from app.core.conversation_state import (
    ConversationMessage,
    ConversationState,
    ConversationStateManager,
    conversation_manager,
    get_conversation_type_from_activity,
    extract_team_channel_ids,
)
from app.core.user_context import UserContext

__all__ = [
    "ConversationMessage",
    "ConversationState",
    "ConversationStateManager",
    "conversation_manager",
    "get_conversation_type_from_activity",
    "extract_team_channel_ids",
    "UserContext",
]
