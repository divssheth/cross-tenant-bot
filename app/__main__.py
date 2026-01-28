# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Cross-Tenant Teams Bot - Main Entry Point

This is a modular, cookiecutter-style Teams bot that you can customize:

Structure:
├── config/          # Configuration and prompts (CUSTOMIZE)
├── core/            # Bot infrastructure (DON'T MODIFY)
│   └── utilities/   # RSC and Teams helpers
├── handlers/        # Command handlers (CUSTOMIZE)
├── agents/          # AI agent implementations (CUSTOMIZE)

To customize:
1. Add commands: Create a new handler in handlers/
2. Change AI: Modify agents/simple_agent.py or create your own
3. Configure: Edit config/settings.py and config/prompts.py

The bot uses:
- Microsoft 365 Agents SDK for Teams integration
- UAMI (User-Assigned Managed Identity) for authentication
- Optional RSC for channel message access
- Pluggable AI agents (default: Microsoft Agent Framework)
"""

import os
import logging

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential

from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.core import (
    AgentApplication,
    TurnState,
    TurnContext,
    MemoryStorage,
    AgentAuthConfiguration,
    AuthTypes,
)
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.activity import load_configuration_from_env, ConversationUpdateTypes

# Load environment variables
load_dotenv()

# Local imports - these must come after dotenv loading
from app.config.settings import settings
from app.log_config import configure_logging
from app.start_server import start_server
from app.core import UserContext
from app.core.utilities.teams_helpers import track_user_message, track_bot_response
from app.handlers import handler_registry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Bot Configuration
# =============================================================================

class BotConfig:
    """Configuration wrapper for the bot."""
    
    def __init__(self):
        """Initialize from settings."""
        self.azure_client_id = settings.AZURE_CLIENT_ID
        self.azure_tenant_id = settings.AZURE_TENANT_ID
        self.microsoft_app_id = settings.MICROSOFT_APP_ID
        self.microsoft_app_type = settings.MICROSOFT_APP_TYPE
        
        # Validate required settings
        missing = []
        if not self.azure_client_id:
            missing.append("AZURE_CLIENT_ID")
        if not self.azure_tenant_id:
            missing.append("AZURE_TENANT_ID")
        if not self.microsoft_app_id:
            missing.append("MICROSOFT_APP_ID")
        
        if missing:
            logger.error(f"❌ Missing required environment variables: {', '.join(missing)}")
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        logger.info(f"Using AZURE_CLIENT_ID (UAMI): {self.azure_client_id}")
        logger.info(f"Using MICROSOFT_APP_ID (Bot): {self.microsoft_app_id}")


# =============================================================================
# Message Handler
# =============================================================================

async def handle_message(context: TurnContext, state: TurnState):
    """
    Main message handler - routes to appropriate command handler.
    
    This function:
    1. Tracks the incoming message in conversation state
    2. Routes to the appropriate handler via the handler registry
    3. Sends the response
    4. Tracks the bot's response in conversation state
    """
    try:
        user_context = UserContext(context)
        user_message = context.activity.text
        
        if not user_message:
            await context.send_activity("No message received.")
            return
        
        # Track incoming message
        track_user_message(context, user_context, user_message)
        
        # Log the message
        logger.info(
            f"Message from {user_context.user_name} | "
            f"{'CROSS-TENANT' if user_context.is_cross_tenant() else 'SAME-TENANT'} | "
            f"Conversation: {user_context.conversation_id[:20]}..."
        )
        
        # Route to handler
        response = await handler_registry.route(context, state, user_message)
        
        if response:
            await context.send_activity(response)
            track_bot_response(context, response)
    
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        await context.send_activity(f"An error occurred: {str(e)}")


async def handle_members_added(context: TurnContext, state: TurnState):
    """
    Handle conversation update when members are added.
    
    Note: In 1:1 (personal) chats, Teams sends this event at the same time as the
    first message, so we skip the welcome to avoid duplicate responses.
    Only send welcome in group chats and channels where users are explicitly added.
    """
    try:
        members_added = context.activity.members_added or []
        bot_id = context.activity.recipient.id if context.activity.recipient else None
        
        # Check if this is a 1:1 (personal) conversation
        conversation = context.activity.conversation
        is_personal = conversation and conversation.conversation_type == "personal"
        
        # Skip welcome message for 1:1 chats
        if is_personal:
            logger.debug("Skipping welcome for 1:1 chat - will respond to first message instead")
            return
        
        # Group chat or channel: Welcome each user that was added
        for member in members_added:
            if bot_id and member.id == bot_id:
                continue
            
            member_name = member.name if member.name else "there"
            
            welcome_message = f"""
👋 **Welcome, {member_name}!**

I'm a cross-tenant Teams bot powered by User-Assigned Managed Identity (UAMI).

**Quick Start:**
• `/help` - Get full command list
• `/ask [question]` - Ask about conversation history
• `/summarize` - Get AI summary

💬 **Or just chat with me!** I'll use conversation context to provide intelligent responses.
""".strip()
            
            await context.send_activity(welcome_message)
            logger.info(f"User {member_name} joined group/channel")
    
    except Exception as e:
        logger.error(f"Error in conversation update: {e}", exc_info=True)


# =============================================================================
# Bot Initialization
# =============================================================================

# Initialize configuration
config = BotConfig()
settings.log_config()

# Create authentication configuration
if config.azure_client_id != config.microsoft_app_id:
    logger.warning("⚠️  AZURE_CLIENT_ID != MICROSOFT_APP_ID")
    logger.warning("   For UserAssignedMSI bots, these should be the SAME (UAMI Client ID)!")

bot_app_id = config.azure_client_id or config.microsoft_app_id or ""

auth_config = AgentAuthConfiguration(
    client_id=bot_app_id,
    tenant_id=config.azure_tenant_id or "",
    auth_type=AuthTypes.user_managed_identity,
    connection_name="SERVICE_CONNECTION"
)

logger.info("=" * 80)
logger.info("UserAssignedMSI CONFIGURATION:")
logger.info(f"  Bot/UAMI App ID: {bot_app_id}")
logger.info(f"  Tenant ID: {config.azure_tenant_id}")
logger.info("=" * 80)

# Check environment
is_local = not (os.getenv("WEBSITE_INSTANCE_ID") or os.getenv("CONTAINER_APP_NAME"))
use_local_auth = settings.LOCAL_DEBUG

if not is_local:
    # Running in Azure - test UAMI
    try:
        test_cred = DefaultAzureCredential(
            managed_identity_client_id=config.azure_client_id
        )
        test_token = test_cred.get_token("https://graph.microsoft.com/.default")
        logger.info("✅ UAMI is accessible and working")
    except Exception as e:
        logger.error(f"❌ UAMI is NOT accessible: {e}")
        raise
else:
    logger.info("⚠️ Running locally - skipping UAMI test")

# Create connection manager
if use_local_auth:
    local_app_id = settings.LOCAL_TEST_APP_ID or settings.GRAPH_APP_ID
    local_app_secret = settings.LOCAL_TEST_APP_SECRET or settings.GRAPH_CLIENT_SECRET
    
    if not local_app_secret:
        raise ValueError("LOCAL_TEST_APP_SECRET or GRAPH_CLIENT_SECRET required for local testing")
    
    logger.info("🔧 LOCAL_DEBUG=true - Using client_secret auth for local testing")
    
    connection_manager = MsalConnectionManager(
        connections_configurations={
            "SERVICE_CONNECTION": {
                "client_id": local_app_id,
                "tenant_id": config.azure_tenant_id,
                "client_secret": local_app_secret,
                "auth_type": AuthTypes.client_secret,
                "connection_name": "SERVICE_CONNECTION",
            }
        }
    )
else:
    connection_manager = MsalConnectionManager(
        connections_configurations={
            "SERVICE_CONNECTION": {
                "client_id": bot_app_id,
                "tenant_id": config.azure_tenant_id or "",
                "auth_type": AuthTypes.user_managed_identity,
                "connection_name": "SERVICE_CONNECTION",
            }
        }
    )

adapter = CloudAdapter(connection_manager=connection_manager)
logger.info("✅ CloudAdapter created")

# Create Agent Application
STORAGE = MemoryStorage()
agents_sdk_config = load_configuration_from_env(dict(os.environ))

AGENT_APP = AgentApplication[TurnState](
    storage=STORAGE,
    adapter=adapter,
    **agents_sdk_config
)
logger.info("✅ Agent application created")

# Register handlers
AGENT_APP.conversation_update(ConversationUpdateTypes.MEMBERS_ADDED)(handle_members_added)
AGENT_APP.activity("message")(handle_message)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    try:
        configure_logging()
        logger.info("Starting cross-tenant bot...")
        logger.info("Bot will be available at http://localhost:3978/api/messages")
        
        logger.info("=" * 80)
        logger.info("FEATURES:")
        logger.info(f"  RSC: {'Enabled' if settings.ENABLE_RSC else 'Disabled'}")
        logger.info(f"  AI:  {'Enabled' if settings.is_ai_available else 'Disabled'}")
        logger.info("=" * 80)
        
        start_server(AGENT_APP, auth_config)
    except Exception as error:
        logger.error(f"Failed to start bot: {error}", exc_info=True)
        raise error
