# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Graph API Client with Application Permissions (RSC) - Multi-Tenant Support

This module provides functions to call Microsoft Graph API using application
permissions (client credentials flow) for cross-tenant RSC access.

Architecture:
- UAMI is used to securely retrieve the client secret from Azure Key Vault
- A multi-tenant app registration with client secret is used for Graph API auth
- This allows the bot to access Graph API in ANY tenant where the app is installed

Flow:
1. UAMI authenticates to Azure Key Vault (no secrets stored in code/config)
2. Client secret is retrieved from Key Vault
3. Client credentials flow authenticates to the TARGET tenant's Graph API
4. RSC permissions (granted at app install) allow channel message access
"""

import os
import asyncio
import aiohttp
import logging
import base64
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from urllib.parse import quote

logger = logging.getLogger(__name__)


def decode_token_claims(token: str) -> Dict[str, Any]:
    """
    Decode JWT token to inspect claims (without verification).
    Useful for debugging permission issues.
    """
    try:
        # JWT has 3 parts: header.payload.signature
        parts = token.split('.')
        if len(parts) != 3:
            return {"error": "Invalid JWT format"}
        
        # Decode payload (2nd part) - add padding if needed
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as e:
        return {"error": f"Failed to decode token: {e}"}


def log_token_claims(token: str, logger) -> None:
    """
    Log key token claims for debugging RSC permission issues.
    
    Key things to check:
    - 'appid': Should match webApplicationInfo.id in manifest
    - 'roles': Should be empty [] for RSC to work (no Azure AD app permissions)
    - 'tid': Should match the tenant where the team exists
    """
    claims = decode_token_claims(token)
    if "error" in claims:
        logger.error(f"Failed to decode token: {claims['error']}")
        return
    
    # Check for Azure AD roles that would override RSC
    roles = claims.get('roles', [])
    if roles:
        logger.warning(f"Token has Azure AD roles: {roles} - these may override RSC!")
        logger.warning("Remove API permissions from Azure AD app registration to use RSC")
    
    logger.debug(f"Token claims: appid={claims.get('appid')}, tid={claims.get('tid')}, roles={roles}")


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Token cache to avoid requesting new tokens for every API call
_token_cache: Dict[str, Dict[str, Any]] = {}

# Client secret cache (retrieved from Key Vault)
_client_secret_cache: Dict[str, str] = {}


async def get_client_secret_from_keyvault() -> Optional[str]:
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
    
    key_vault_name = os.getenv("KEY_VAULT_NAME")
    secret_name = os.getenv("GRAPH_CLIENT_SECRET_NAME", "graph-client-secret")
    
    if not key_vault_name:
        # Fallback: check for direct environment variable (for local dev only)
        direct_secret = os.getenv("GRAPH_CLIENT_SECRET")
        if direct_secret:
            logger.warning("Using GRAPH_CLIENT_SECRET from env (not recommended for production)")
            return direct_secret
        logger.error("KEY_VAULT_NAME not set and no GRAPH_CLIENT_SECRET fallback")
        return None
    
    try:
        from azure.identity import ManagedIdentityCredential
        from azure.keyvault.secrets import SecretClient
        
        # Use UAMI to authenticate to Key Vault
        uami_client_id = os.getenv("AZURE_CLIENT_ID")
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
        _client_secret_cache[cache_key] = secret.value
        return secret.value
        
    except Exception as e:
        logger.error(f"Failed to retrieve secret from Key Vault: {e}")
        logger.error("Ensure UAMI has 'Key Vault Secrets User' role on the Key Vault")
        return None


async def get_app_token(tenant_id: Optional[str] = None) -> Optional[str]:
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
        tenant_id = os.getenv("AZURE_TENANT_ID")
        if not tenant_id:
            logger.error("tenant_id is required for cross-tenant Graph API access")
            return None
    
    graph_app_id = os.getenv("GRAPH_APP_ID")
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
    client_secret = await get_client_secret_from_keyvault()
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


async def get_channel_messages_rsc(
    team_id: str,
    channel_id: str,
    top: int = 50,
    tenant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get messages from a Teams channel using RSC (application permissions).
    
    This does NOT require user authentication - uses client credentials flow.
    
    REQUIRES: ChannelMessage.Read.Group RSC permission (granted at team install)
    
    IMPORTANT:
    - team_id must be the M365 Group ID (GUID format), NOT 19:xxx format
    - channel_id should be in format 19:xxx@thread.tacv2
    - RSC requires the /beta endpoint for channel messages
    
    Args:
        team_id: The M365 Group ID of the team (GUID format)
        channel_id: The ID of the channel (19:xxx@thread.tacv2)
        top: Maximum number of messages to retrieve (default 50)
        tenant_id: Optional tenant ID for cross-tenant scenarios
        
    Returns:
        List of message dictionaries
    """
    if not team_id:
        logger.error("team_id (M365 Group ID) is required for Graph API access")
        return []
    
    if not channel_id or not channel_id.startswith("19:"):
        logger.warning(f"channel_id '{channel_id}' may not be in expected format (should start with '19:')")
    
    # URL encode the channel_id since it contains special characters like @ and :
    encoded_channel_id = quote(channel_id, safe='')
    
    token = await get_app_token(tenant_id)
    if not token:
        logger.error("Could not get app token for channel messages")
        return []
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        # RSC permissions require the BETA endpoint for channel messages
        url = f"https://graph.microsoft.com/beta/teams/{team_id}/channels/{encoded_channel_id}/messages?$top={top}"
        
        logger.debug(f"Fetching channel messages: team={team_id}, channel={channel_id[:20]}...")
        
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                messages = data.get("value", [])
                logger.info(f"Retrieved {len(messages)} messages from channel")
                return messages
            elif response.status == 403:
                error_text = await response.text()
                logger.error(f"RSC 403 Error: {error_text}")
                logger.error("Possible causes: 1) App not installed in team, 2) RSC not consented, 3) Wrong team_id format (must be M365 Group GUID)")
                # Log token claims for debugging when 403 occurs
                log_token_claims(token, logger)
                return []
            else:
                error_text = await response.text()
                logger.error(f"Error getting channel messages: {response.status} - {error_text}")
                return []


async def get_message_replies_rsc(
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
    token = await get_app_token(tenant_id)
    if not token:
        logger.error("Could not get app token for message replies")
        return []
    
    # URL encode the channel_id since it contains special characters
    encoded_channel_id = quote(channel_id, safe='')
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        # RSC permissions require the BETA endpoint for channel messages
        url = f"https://graph.microsoft.com/beta/teams/{team_id}/channels/{encoded_channel_id}/messages/{message_id}/replies?$top={top}"
        
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


async def get_channel_messages_with_replies_rsc(
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
    messages = await get_channel_messages_rsc(team_id, channel_id, top, tenant_id)
    
    if not include_replies or not messages:
        return messages
    
    # Fetch replies for each message that has them
    for msg in messages:
        message_id = msg.get("id")
        reply_count = msg.get("replyToId") is None  # Only fetch replies for top-level messages
        
        if message_id and reply_count:
            replies = await get_message_replies_rsc(
                team_id, channel_id, message_id, 
                top=max_replies_per_message, 
                tenant_id=tenant_id
            )
            msg["replies"] = replies
    
    logger.info(f"Retrieved {len(messages)} messages with replies from channel {channel_id[:8]}...")
    return messages


async def get_team_info(
    team_id: str,
    tenant_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Get information about a team.
    
    Args:
        team_id: The ID of the team
        tenant_id: Optional tenant ID for cross-tenant scenarios
        
    Returns:
        Team information dictionary, or None if failed
    """
    token = await get_app_token(tenant_id)
    if not token:
        return None
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        async with session.get(
            f"{GRAPH_BASE_URL}/teams/{team_id}",
            headers=headers
        ) as response:
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                logger.error(f"Error getting team info: {response.status} - {error_text}")
                return None


async def get_channel_info(
    team_id: str,
    channel_id: str,
    tenant_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Get information about a channel.
    
    Args:
        team_id: The ID of the team
        channel_id: The ID of the channel
        tenant_id: Optional tenant ID for cross-tenant scenarios
        
    Returns:
        Channel information dictionary, or None if failed
    """
    token = await get_app_token(tenant_id)
    if not token:
        return None
    
    # URL encode the channel_id since it contains special characters
    encoded_channel_id = quote(channel_id, safe='')
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        async with session.get(
            f"{GRAPH_BASE_URL}/teams/{team_id}/channels/{encoded_channel_id}",
            headers=headers
        ) as response:
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                logger.error(f"Error getting channel info: {response.status} - {error_text}")
                return None


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
    token = await get_app_token(tenant_id)
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
    
    import re
    
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
