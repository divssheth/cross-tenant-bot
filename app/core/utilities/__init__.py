# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Core Utilities - Helper functions for bot operations.

This module contains utility functions that can be imported by handlers.
"""

from app.core.utilities.rsc import (
    get_channel_messages,
    get_channel_messages_with_replies,
    get_message_replies,
    get_channel_context,
    get_user_by_id,
    format_messages_for_context,
    is_rsc_enabled,
)
from app.core.utilities.teams_helpers import (
    is_channel_conversation,
    get_conversation_context,
)

__all__ = [
    # RSC utilities
    "get_channel_messages",
    "get_channel_messages_with_replies",
    "get_message_replies",
    "get_channel_context",
    "get_user_by_id",
    "format_messages_for_context",
    "is_rsc_enabled",
    # Teams helpers
    "is_channel_conversation",
    "get_conversation_context",
]
