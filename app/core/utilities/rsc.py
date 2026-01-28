# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
RSC Utility - Resource-Specific Consent for reading channel messages.

Use this utility in your handlers when you need channel conversation context.
Requires ENABLE_RSC=true and proper RSC permissions in manifest.

Example usage in a handler:
    from app.core.utilities.rsc import get_channel_context, is_rsc_enabled
    
    class MyHandler(CommandHandler):
        async def handle(self, context, state, args):
            if is_rsc_enabled() and is_channel_conversation(context):
                messages = await get_channel_context(context, max_messages=20)
                # Use messages for AI context
"""

import re
import asyncio
import aiohttp
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from app.config.settings import settings

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Token cache to avoid requesting new tokens for every API call
_token_cache: Dict[str, Dict[str, Any]] = {}

# Client secret cache (retrieved from Key Vault)
_client_secret_cache: Dict[str, str] = {}


def is_rsc_enabled() -> bool:
    """Check if RSC is enabled and configured."""
    return settings.ENABLE_RSC and bool(settings.GRAPH_APP_ID)


async def _get_client_secret_from_keyvault() -> Optional[str]:
    """
    Retrieve the Graph API client secret from Azure Key Vault using UAMI.
    
    The UAMI authenticates to Key Vault without any secrets - this is the secure
    way to retrieve the client secret needed for cross-tenant Graph API access.
    
    Returns:
        The client secret value, or None if not available
    """
    # Check cache first
    cache_key = "graph_client_secret"
    if cache_key in _client_secret_cache:
        return _client_secret_cache[cache_key]
    
    key_vault_name = settings.KEY_VAULT_NAME
    secret_name = settings.GRAPH_CLIENT_SECRET_NAME
    
    if not key_vault_name:
        # Fallback: check for direct environment variable (for local dev only)
        direct_secret = settings.GRAPH_CLIENT_SECRET
        if direct_secret:
            logger.warning("Using GRAPH_CLIENT_SECRET from env (not recommended for production)")
            return direct_secret
        logger.error("KEY_VAULT_NAME not set and no GRAPH_CLIENT_SECRET fallback")
        return None
    
    try:
        from azure.identity import ManagedIdentityCredential
        from azure.keyvault.secrets import SecretClient
        
        # Use UAMI to authenticate to Key Vault
        uami_client_id = settings.AZURE_CLIENT_ID
        credential = ManagedIdentityCredential(client_id=uami_client_id)
        
        vault_url = f"https://{key_vault_name}.vault.azure.net"
        client = SecretClient(vault_url=vault_url, credential=credential)
        
        # Run sync operation in executor
        loop = asyncio.get_event_loop()
        secret = await loop.run_in_executor(
            None,
            lambda: client.get_secret(secret_name)
        )
        
        logger.info(f"Successfully retrieved secret '{secret_name}' from Key Vault")
        
        # Cache the secret
        if secret.value:
            _client_secret_cache[cache_key] = secret.value
        return secret.value
        
    except Exception as e:
        logger.error(f"Failed to retrieve secret from Key Vault: {e}")
        logger.error("Ensure UAMI has 'Key Vault Secrets User' role on the Key Vault")
        return None


async def _get_app_token(tenant_id: Optional[str] = None) -> Optional[str]:
    """
    Get an application token for Graph API using client credentials flow.
    
    This authenticates to the SPECIFIED tenant, allowing cross-tenant access
    when the multi-tenant app is installed in that tenant.
    
    Args:
        tenant_id: The tenant ID to authenticate to. Falls back to AZURE_TENANT_ID if not provided.
        
    Returns:
        Access token string, or None if failed
    """
    if not tenant_id:
        tenant_id = settings.AZURE_TENANT_ID
        if not tenant_id:
            logger.error("tenant_id is required for cross-tenant Graph API access")
            return None
    
    graph_app_id = settings.GRAPH_APP_ID
    if not graph_app_id:
        logger.error("GRAPH_APP_ID must be set (multi-tenant app registration Client ID)")
        return None
    
    # Check token cache
    cache_key = f"graph:{tenant_id}:{graph_app_id}"
    if cache_key in _token_cache:
        cached = _token_cache[cache_key]
        if cached["expires_at"] > datetime.now():
            logger.debug(f"Using cached Graph API token for tenant {tenant_id[:8]}...")
            return cached["token"]
    
    # Get client secret from Key Vault
    client_secret = await _get_client_secret_from_keyvault()
    if not client_secret:
        logger.error("Could not retrieve client secret - cannot authenticate to Graph API")
        return None
    
    # Request token using client credentials flow to the TARGET tenant
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    
    async with aiohttp.ClientSession() as session:
        data = {
            "grant_type": "client_credentials",
            "client_id": graph_app_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default"
        }
        
        async with session.post(token_url, data=data) as response:
            if response.status == 200:
                result = await response.json()
                token = result.get("access_token")
                expires_in = result.get("expires_in", 3600)
                
                # Cache the token (with 5 minute buffer)
                _token_cache[cache_key] = {
                    "token": token,
                    "expires_at": datetime.now() + timedelta(seconds=expires_in - 300)
                }
                
                logger.info(f"Successfully obtained Graph API token for tenant {tenant_id[:8]}...")
                return token
            else:
                error_text = await response.text()
                logger.error(f"Failed to get Graph API token: {response.status} - {error_text}")
                if response.status == 400:
                    logger.error("Check that GRAPH_APP_ID is correct and app is multi-tenant")
                elif response.status == 401:
                    logger.error("Check that client secret is correct and not expired")
                return None


async def get_channel_messages(
    team_id: str,
    channel_id: str,
    top: int = 50,
    tenant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get messages from a Teams channel using RSC (application permissions).
    
    This does NOT require user authentication - uses client credentials flow.
    
    REQUIRES: ChannelMessage.Read.Group RSC permission (granted at team install)
    
    Args:
        team_id: The ID of the team
        channel_id: The ID of the channel
        top: Maximum number of messages to retrieve (default 50)
        tenant_id: Optional tenant ID for cross-tenant scenarios
        
    Returns:
        List of message dictionaries
    """
    if not is_rsc_enabled():
        logger.warning("RSC is not enabled - cannot get channel messages")
        return []
    
    token = await _get_app_token(tenant_id)
    if not token:
        logger.error("Could not get app token for channel messages")
        return []
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        # RSC permissions require the BETA endpoint for channel messages
        url = f"https://graph.microsoft.com/beta/teams/{team_id}/channels/{channel_id}/messages?$top={top}"
        
        # Log the request details for debugging RSC issues
        logger.info(f"RSC Request - Team: {team_id}, Channel: {channel_id}, Tenant: {tenant_id}")
        logger.debug(f"RSC URL: {url}")
        
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                messages = data.get("value", [])
                logger.info(f"Retrieved {len(messages)} messages from channel {channel_id[:8]}...")
                return messages
            elif response.status == 403:
                error_text = await response.text()
                logger.error(f"RSC 403 Error - Team: {team_id}, Channel: {channel_id}, Tenant: {tenant_id}")
                logger.error(f"RSC 403 Response: {error_text}")
                logger.error("Possible causes: 1) App not installed in this team, 2) RSC not consented, 3) Wrong app ID in webApplicationInfo")
                return []
            else:
                error_text = await response.text()
                logger.error(f"Error getting channel messages: {response.status} - {error_text}")
                return []


async def get_message_replies(
    team_id: str,
    channel_id: str,
    message_id: str,
    top: int = 50,
    tenant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get replies to a specific message in a Teams channel using RSC (application permissions).
    
    This does NOT require user authentication - uses client credentials flow.
    
    REQUIRES: ChannelMessage.Read.Group RSC permission (granted at team install)
    
    Args:
        team_id: The ID of the team
        channel_id: The ID of the channel
        message_id: The ID of the parent message to get replies for
        top: Maximum number of replies to retrieve (default 50)
        tenant_id: Optional tenant ID for cross-tenant scenarios
        
    Returns:
        List of reply message dictionaries
    """
    if not is_rsc_enabled():
        return []
    
    token = await _get_app_token(tenant_id)
    if not token:
        logger.error("Could not get app token for message replies")
        return []
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        # RSC permissions require the BETA endpoint for channel messages
        url = f"https://graph.microsoft.com/beta/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies?$top={top}"
        
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                replies = data.get("value", [])
                logger.info(f"Retrieved {len(replies)} replies for message {message_id[:8]}...")
                return replies
            elif response.status == 403:
                error_text = await response.text()
                logger.warning(f"Access denied to message replies. Ensure RSC permissions are granted: {error_text}")
                return []
            else:
                error_text = await response.text()
                logger.error(f"Error getting message replies: {response.status} - {error_text}")
                return []


async def get_channel_messages_with_replies(
    team_id: str,
    channel_id: str,
    top: int = 20,
    include_replies: bool = True,
    max_replies_per_message: int = 10,
    tenant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get messages from a Teams channel including their replies.
    
    This fetches top-level messages and optionally fetches replies for each.
    
    REQUIRES: ChannelMessage.Read.Group RSC permission (granted at team install)
    
    Args:
        team_id: The ID of the team
        channel_id: The ID of the channel
        top: Maximum number of top-level messages to retrieve (default 20)
        include_replies: Whether to fetch replies for each message (default True)
        max_replies_per_message: Maximum replies to fetch per message (default 10)
        tenant_id: Optional tenant ID for cross-tenant scenarios
        
    Returns:
        List of message dictionaries, each with a 'replies' field if include_replies=True
    """
    # Get top-level messages
    messages = await get_channel_messages(team_id, channel_id, top, tenant_id)
    
    if not include_replies or not messages:
        return messages
    
    # Fetch replies for each message that has them
    for msg in messages:
        message_id = msg.get("id")
        reply_count = msg.get("replyToId") is None  # Only fetch replies for top-level messages
        
        if message_id and reply_count:
            replies = await get_message_replies(
                team_id, channel_id, message_id, 
                top=max_replies_per_message, 
                tenant_id=tenant_id
            )
            msg["replies"] = replies
    
    logger.info(f"Retrieved {len(messages)} messages with replies from channel {channel_id[:8]}...")
    return messages


async def get_channel_context(
    context,
    max_messages: int = 20,
    include_replies: bool = True
) -> str:
    """
    Convenience function: Get formatted channel context from a TurnContext.
    
    Extracts team/channel IDs from the context and returns formatted messages.
    
    Args:
        context: TurnContext from the bot
        max_messages: Maximum messages to fetch
        include_replies: Whether to include reply threads
        
    Returns:
        Formatted string of channel messages
    """
    from app.core import extract_team_channel_ids, get_conversation_type_from_activity
    from app.core.user_context import UserContext
    
    conv_type = get_conversation_type_from_activity(context.activity)
    team_id, channel_id = extract_team_channel_ids(context.activity)
    
    if conv_type != "channel" or not team_id or not channel_id:
        return "Not a channel conversation or missing team/channel IDs."
    
    if not is_rsc_enabled():
        return "RSC is not enabled."
    
    user_context = UserContext(context)
    tenant_id = user_context.user_tenant_id or settings.AZURE_TENANT_ID
    
    messages = await get_channel_messages_with_replies(
        team_id=team_id,
        channel_id=channel_id,
        top=max_messages,
        include_replies=include_replies,
        tenant_id=tenant_id
    )
    
    return format_messages_for_context(messages, max_messages=max_messages, include_replies=include_replies)


async def get_user_by_id(
    user_id: str,
    tenant_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Get user information by their AAD Object ID.
    
    REQUIRES: User.Read.All application permission
    
    Args:
        user_id: The user's AAD Object ID
        tenant_id: Optional tenant ID for cross-tenant scenarios
        
    Returns:
        User information dictionary, or None if failed
    """
    if not is_rsc_enabled():
        return None
    
    token = await _get_app_token(tenant_id)
    if not token:
        return None
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        async with session.get(
            f"{GRAPH_BASE_URL}/users/{user_id}",
            headers=headers
        ) as response:
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                logger.error(f"Error getting user info: {response.status} - {error_text}")
                return None


def format_messages_for_context(
    messages: List[Dict[str, Any]],
    max_messages: int = 10,
    include_replies: bool = True
) -> str:
    """
    Format Graph API messages into a readable context string.
    
    Args:
        messages: List of message dictionaries from Graph API
        max_messages: Maximum number of messages to include
        include_replies: Whether to include replies in the output
        
    Returns:
        Formatted string of messages
    """
    if not messages:
        return "No messages available."
    
    # Take most recent messages (Graph returns newest first)
    recent = messages[:max_messages]
    
    def clean_content(content: str) -> str:
        """Clean HTML content and truncate."""
        content = re.sub(r'<[^>]+>', '', content).strip()
        if len(content) > 200:
            content = content[:200] + "..."
        return content
    
    lines = []
    for msg in reversed(recent):  # Reverse to show oldest first
        sender = msg.get("from", {}).get("user", {}).get("displayName", "Unknown")
        content = msg.get("body", {}).get("content", "")
        
        # Clean HTML content
        content = clean_content(content)
        
        if content:
            lines.append(f"**{sender}**: {content}")
        
        # Include replies if available
        if include_replies and "replies" in msg:
            replies = msg.get("replies", [])
            for reply in replies:
                reply_sender = reply.get("from", {}).get("user", {}).get("displayName", "Unknown")
                reply_content = reply.get("body", {}).get("content", "")
                reply_content = clean_content(reply_content)
                
                if reply_content:
                    lines.append(f"  ↳ **{reply_sender}**: {reply_content}")
    
    return "\n".join(lines) if lines else "No message content available."
