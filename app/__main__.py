"""
Cross-Tenant Teams Bot with User-Assigned Managed Identity
Sample Implementation using Microsoft 365 Agents SDK

Features:
- UAMI authentication for Bot Framework
- RSC permissions for reading channel messages
- Conversation state for 1:1 and group chat context
- No user authentication required for context reading
"""

# Standard library imports
import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict

# Third-party imports
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential

# Microsoft Agents SDK imports
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
from microsoft_agents.activity import load_configuration_from_env, ConversationUpdateTypes, ActivityTypes

# Local imports
from app.log_config import configure_logging
from app.start_server import start_server
from app.conversation_state import (
    conversation_manager,
    get_conversation_type_from_activity,
    extract_team_channel_ids,
    extract_team_info_for_caching,
    team_mapping_cache,
)
from app.graph_rsc_client import (
    get_channel_messages_rsc,
    get_channel_messages_with_replies_rsc,
    get_message_replies_rsc,
    get_user_by_id,
    format_messages_for_context,
)

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BotConfig:
    """
    Configuration for the cross-tenant bot using UAMI.

    All values are read from environment variables set in Azure App Service.
    Note: No client secrets are stored or needed.
    """

    def __init__(self):
        """Initialize configuration from environment variables."""
        
        # Log environment variable status
        logger.info("=" * 80)
        logger.info("READING ENVIRONMENT VARIABLES:")
        logger.info(f"  AZURE_CLIENT_ID env var set: {bool(os.getenv('AZURE_CLIENT_ID'))}")
        logger.info(f"  AZURE_TENANT_ID env var set: {bool(os.getenv('AZURE_TENANT_ID'))}")
        logger.info(f"  MICROSOFT_APP_ID env var set: {bool(os.getenv('MICROSOFT_APP_ID'))}")
        logger.info("=" * 80)

        # UAMI Client ID (from Step 1 of setup guide)
        # No default - must be set via environment variable
        self.azure_client_id: Optional[str] = os.getenv("AZURE_CLIENT_ID")

        # Azure Tenant ID (from Step 2 of setup guide)
        # No default - must be set via environment variable
        self.azure_tenant_id: Optional[str] = os.getenv("AZURE_TENANT_ID")

        # Microsoft App ID (from Step 2 of setup guide)
        # No default - must be set via environment variable
        self.microsoft_app_id: Optional[str] = os.getenv("MICROSOFT_APP_ID")
        
        # Validate required configuration
        missing = []
        if not self.azure_client_id:
            missing.append("AZURE_CLIENT_ID")
        if not self.azure_tenant_id:
            missing.append("AZURE_TENANT_ID")
        if not self.microsoft_app_id:
            missing.append("MICROSOFT_APP_ID")
        
        if missing:
            logger.error(f"❌ Missing required environment variables: {', '.join(missing)}")
            logger.error("Set these environment variables before running:")
            logger.error("  PowerShell: $env:AZURE_CLIENT_ID='your-uami-client-id'")
            logger.error("  Bash: export AZURE_CLIENT_ID='your-uami-client-id'")
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        logger.info(f"Using AZURE_CLIENT_ID (UAMI): {self.azure_client_id}")
        logger.info(f"Using MICROSOFT_APP_ID (Bot): {self.microsoft_app_id}")

        # Bot type - SingleTenant with UAMI. Azure Bot Service handles cross-tenant routing.
        self.microsoft_app_type: str = os.getenv("MICROSOFT_APP_TYPE", "SingleTenant")

        # Messaging endpoint (automatically configured in Azure Bot resource)
        self.messaging_endpoint: str = os.getenv(
            "MESSAGING_ENDPOINT",
            "https://localhost:8080/api/messages"
        )

        # Azure Identity credential - automatically uses UAMI when in App Service
        self.credential: Optional[DefaultAzureCredential] = None
        try:
            self.credential = DefaultAzureCredential(managed_identity_client_id=self.azure_client_id)
            logger.info("Azure Identity credential initialized (UAMI mode)")
        except Exception as e:
            logger.warning(f"Could not initialize Azure credential: {e}")

    def validate(self) -> bool:
        """Validate that all required configuration values are set."""
        # For local testing, we may not have all values
        return True

    def log_config(self):
        """Log configuration values for debugging (excluding sensitive data)."""
        logger.info("=== Bot Configuration ===")
        if self.azure_client_id:
            logger.info(f"Azure Client ID: {self.azure_client_id[:8]}...")
        else:
            logger.info("Azure Client ID: Not set (using anonymous mode)")
        if self.azure_tenant_id:
            logger.info(f"Azure Tenant ID: {self.azure_tenant_id[:8]}...")
        else:
            logger.info("Azure Tenant ID: Not set")
        if self.microsoft_app_id:
            logger.info(f"Microsoft App ID: {self.microsoft_app_id[:8]}...")
        else:
            logger.info("Microsoft App ID: Not set (using anonymous mode)")
        logger.info(f"Bot Type: {self.microsoft_app_type}")
        logger.info(f"Messaging Endpoint: {self.messaging_endpoint}")
        logger.info("========================")


class UserContext:
    """
    Encapsulates information about a user sending a message.

    Tracks user details, tenant information, and conversation context.
    """

    def __init__(self, turn_context: TurnContext):
        """Initialize user context from the Teams activity."""
        self.user_id: str = turn_context.activity.from_property.id if turn_context.activity.from_property else "unknown"
        self.user_name: str = turn_context.activity.from_property.name if turn_context.activity.from_property else "Unknown User"
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


class CrossTenantBot:
    """
    Main bot implementation.

    Handles incoming messages and conversation updates from users
    in multiple tenants. Uses UAMI for secure, secret-free authentication.
    """

    def __init__(self, config: BotConfig):
        """Initialize the bot with configuration."""
        self.config = config
        self.user_sessions: Dict[str, UserContext] = {}
        logger.info("Bot initialized")

    async def on_message_activity(self, context: TurnContext, state: TurnState):
        """
        Handle incoming message activities.

        This method is called whenever a user sends a message to the bot.
        Messages are tracked in conversation state for context.
        """
        try:
            # Extract user context
            user_context = UserContext(context)

            # Log the incoming message
            self._log_message_received(user_context)

            # Store user session for reference
            self.user_sessions[user_context.user_id] = user_context

            # Get the user's message text
            user_message = context.activity.text
            if not user_message:
                await context.send_activity("No message received.")
                return

            # Track message in conversation state (for 1:1 and group chats)
            conversation_id = context.activity.conversation.id if context.activity.conversation else None
            if conversation_id:
                conv_type = get_conversation_type_from_activity(context.activity)
                team_id, channel_id = extract_team_channel_ids(context.activity)
                
                conversation_manager.add_user_message(
                    conversation_id=conversation_id,
                    sender_id=user_context.user_id,
                    sender_name=user_context.user_name,
                    text=user_message,
                    message_id=context.activity.id or "",
                    conversation_type=conv_type,
                    team_id=team_id,
                    channel_id=channel_id,
                    tenant_id=user_context.user_tenant_id
                )

            # Convert to lowercase for command parsing
            message_lower = user_message.lower().strip()

            # Route to appropriate handler based on message content
            if message_lower == "/help":
                response = await self._handle_help(user_context)

            elif message_lower == "/info":
                response = await self._handle_info(user_context)

            elif message_lower == "/status":
                response = await self._handle_status(user_context)

            elif message_lower == "/context":
                response = await self._handle_context(context, user_context)

            elif message_lower == "/contextinfo":
                response = await self._handle_context_info(context)

            elif message_lower == "/rsctest":
                response = await self._handle_rsc_test(context, user_context)

            elif message_lower == "/teamcache":
                response = await self._handle_team_cache(context)

            elif message_lower.startswith("/whois "):
                user_id = user_message[7:].strip()
                response = await self._handle_whois(context, user_id)

            elif message_lower.startswith("/echo "):
                response = await self._handle_echo(user_message[6:], user_context)

            else:
                response = await self._handle_default(user_message, user_context)

            # Send the response back to the user
            await context.send_activity(response)

            # Track bot response in conversation state
            if conversation_id:
                conversation_manager.add_bot_message(
                    conversation_id=conversation_id,
                    text=response[:200] + "..." if len(response) > 200 else response
                )

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            error_response = f"An error occurred processing your message: {str(e)}"
            await context.send_activity(error_response)

    async def on_members_added(self, context: TurnContext, state: TurnState):
        """
        Handle conversation update when members are added.

        This method is called when members join the conversation.
        When the bot is added to a team, we cache the aadGroupId mapping
        for later use when processing channel messages.
        """
        try:
            user_context = UserContext(context)

            # Log member join
            logger.info(
                f"User {user_context.user_name} "
                f"({user_context.user_id}) joined"
            )
            
            # Extract and cache team info if this is a team context
            # The aadGroupId is only available in conversationUpdate events
            team_info = extract_team_info_for_caching(context.activity)
            
            if team_info.get("thread_id") and team_info.get("aad_group_id"):
                # Cache the mapping for later use
                team_mapping_cache.add_mapping(
                    thread_id=team_info["thread_id"],
                    aad_group_id=team_info["aad_group_id"],
                    tenant_id=team_info.get("tenant_id"),
                    team_name=team_info.get("team_name")
                )
                logger.info(
                    f"✅ Team mapping cached successfully: "
                    f"{team_info['team_name'] or 'Unknown Team'}"
                )
            elif team_info.get("thread_id"):
                # We have a thread_id but no aadGroupId - log this for debugging
                logger.warning(
                    f"⚠️ conversationUpdate received but no aadGroupId found. "
                    f"thread_id: {team_info['thread_id'][:30]}..., "
                    f"eventType: {team_info.get('event_type')}"
                )

            # Send welcome message
            welcome_message = self._build_welcome_message(user_context)
            await context.send_activity(welcome_message)

        except Exception as e:
            logger.error(f"Error in conversation update: {e}", exc_info=True)

    # Message handlers

    async def _handle_help(self, user_context: UserContext) -> str:
        """Handle help command."""
        help_text = """
**Available Commands:**

📋 **Basic Commands:**
• `/help` - Shows this help message
• `/info` - Displays your user and tenant information
• `/status` - Shows bot status
• `/echo [text]` - Echoes back the text you provide

📚 **Context Commands (No Sign-in Required):**
• `/context` - Shows recent conversation context
• `/contextinfo` - Shows conversation state information
• `/rsctest` - Diagnose RSC permissions (use in a channel)
• `/teamcache` - Shows team mapping cache status

Or simply type any message and I'll respond.
"""
        return help_text.strip()

    async def _handle_info(self, user_context: UserContext) -> str:
        """Handle info command - shows user context."""
        ctx = user_context.to_dict()

        cross_tenant_status = (
            "Yes - Cross-tenant communication"
            if ctx['is_cross_tenant']
            else "No - Same tenant"
        )

        info_text = f"""
**User Information:**

• **Name:** {ctx['user_name']}
• **User ID:** {ctx['user_id']}
• **User Tenant:** {ctx['user_tenant']}
• **Bot Tenant:** {ctx['bot_tenant']}
• **Cross-Tenant:** {cross_tenant_status}
• **Conversation ID:** {ctx['conversation_id']}
• **Message Time:** {ctx['timestamp']}
"""
        return info_text.strip()

    async def _handle_status(self, user_context: UserContext) -> str:
        """Handle status command - shows bot status."""
        active_sessions = len([
            s for s in self.user_sessions.values()
            if s.timestamp
        ])

        tenant_id = os.getenv("AZURE_TENANT_ID", "unknown")
        tenant_display = tenant_id[:20] + "..." if len(tenant_id) > 20 else tenant_id

        # Get conversation stats
        conv_stats = conversation_manager.get_stats()

        status_text = f"""
**Bot Status:**

• **Status:** Online and responding ✅
• **Active Sessions:** {active_sessions}
• **Bot Tenant ID:** {tenant_display}
• **Authentication:** User-Assigned Managed Identity (UAMI)

**Conversation State:**
• **Total Conversations:** {conv_stats['total_conversations']}
• **Personal Chats:** {conv_stats['personal_chats']}
• **Group Chats:** {conv_stats['group_chats']}
• **Channels:** {conv_stats['channels']}
• **Messages Stored:** {conv_stats['total_messages_stored']}
"""
        return status_text.strip()

    async def _handle_echo(self, message: str, user_context: UserContext) -> str:
        """Handle echo command - echoes back user text."""
        if not message.strip():
            return "Please provide text to echo."

        echo_response = f"🔊 **Echo:** {message}"

        if user_context.is_cross_tenant() and user_context.user_tenant_id:
            echo_response += f"\n\n_(Cross-tenant message from {user_context.user_tenant_id[:20]}...)_"

        return echo_response

    async def _handle_context(self, context: TurnContext, user_context: UserContext) -> str:
        """
        Handle /context command - show recent conversation context.
        
        For 1:1 and group chats: Uses in-memory conversation state
        For channels: Uses RSC to fetch from Graph API
        """
        conversation_id = context.activity.conversation.id if context.activity.conversation else None
        
        if not conversation_id:
            return "❌ Could not determine conversation ID."
        
        # Get conversation type
        conv_type = get_conversation_type_from_activity(context.activity)
        team_id, channel_id = extract_team_channel_ids(context.activity)
        
        # Get tenant ID for cross-tenant scenarios
        tenant_id = user_context.user_tenant_id or os.getenv("AZURE_TENANT_ID")
        
        logger.debug(f"Context command: type={conv_type}, team_id={team_id}, channel_id={channel_id[:20] if channel_id else None}...")
        
        if conv_type == "channel" and team_id and channel_id:
            # For channels, use RSC to get messages from Graph API
            try:
                max_messages = int(os.getenv("MAX_GRAPH_MESSAGES", "20"))
                messages = await get_channel_messages_with_replies_rsc(
                    team_id=team_id,
                    channel_id=channel_id,
                    top=max_messages,
                    include_replies=True,
                    max_replies_per_message=10,
                    tenant_id=tenant_id
                )
                
                if messages:
                    context_str = format_messages_for_context(messages, max_messages=10, include_replies=True)
                    return f"""
**📚 Channel Context (from Graph API via RSC):**

{context_str}

_Retrieved {len(messages)} messages from channel history_
""".strip()
                else:
                    return "No channel messages found. Ensure RSC permissions are granted and the bot is installed in this team."
                    
            except Exception as e:
                logger.error(f"Error getting channel context: {e}", exc_info=True)
                return f"❌ Error retrieving channel context: {str(e)}"
        
        else:
            # For 1:1 and group chats, use in-memory conversation state
            conversation_context = conversation_manager.get_context(conversation_id, limit=10)
            
            if conversation_context == "No conversation history available.":
                return """
**📚 Conversation Context:**

No messages stored yet. Send some messages and then try `/context` again.

_Note: Context is stored in memory and resets when the bot restarts._
""".strip()
            
            return f"""
**📚 Conversation Context ({conv_type}):**

{conversation_context}

_Showing last 10 messages from this conversation_
""".strip()

    async def _handle_context_info(self, context: TurnContext) -> str:
        """Handle /contextinfo command - show conversation state information."""
        conversation_id = context.activity.conversation.id if context.activity.conversation else None
        
        if not conversation_id:
            return "❌ Could not determine conversation ID."
        
        info = conversation_manager.get_conversation_info(conversation_id)
        
        if not info.get("exists"):
            return "No conversation state exists for this chat yet."
        
        return f"""
**📊 Conversation State Info:**

• **Type:** {info.get('type', 'unknown')}
• **Messages Stored:** {info.get('message_count', 0)}
• **Team ID:** {info.get('team_id', 'N/A')[:20] + '...' if info.get('team_id') else 'N/A'}
• **Channel ID:** {info.get('channel_id', 'N/A')[:20] + '...' if info.get('channel_id') else 'N/A'}
• **Tenant ID:** {info.get('tenant_id', 'N/A')[:20] + '...' if info.get('tenant_id') else 'N/A'}
• **Created:** {info.get('created_at', 'N/A')}
• **Last Activity:** {info.get('last_activity', 'N/A')}
""".strip()

    async def _handle_rsc_test(self, context: TurnContext, user_context: UserContext) -> str:
        """
        Handle /rsctest command - diagnose RSC permissions.
        
        This command helps identify why RSC might not be working.
        """
        conv_type = get_conversation_type_from_activity(context.activity)
        team_id, channel_id = extract_team_channel_ids(context.activity)
        tenant_id = user_context.user_tenant_id or os.getenv("AZURE_TENANT_ID")
        graph_app_id = os.getenv("GRAPH_APP_ID", "Not set")
        
        diagnostics = []
        diagnostics.append("**🔍 RSC Diagnostic Test**\n")
        
        # Check conversation type
        diagnostics.append(f"**Conversation Type:** {conv_type}")
        if conv_type != "channel":
            diagnostics.append("⚠️ RSC only works in channels, not 1:1 or group chats")
            return "\n".join(diagnostics)
        
        # Check team and channel IDs
        diagnostics.append(f"**Team ID:** `{team_id or 'NOT FOUND'}`")
        diagnostics.append(f"**Channel ID:** `{channel_id or 'NOT FOUND'}`")
        diagnostics.append(f"**Tenant ID:** `{tenant_id or 'NOT FOUND'}`")
        diagnostics.append(f"**Graph App ID:** `{graph_app_id[:20]}...`" if len(graph_app_id) > 20 else f"**Graph App ID:** `{graph_app_id}`")
        
        if not team_id or not channel_id:
            diagnostics.append("\n❌ **ERROR:** Could not extract Team/Channel IDs from activity")
            return "\n".join(diagnostics)
        
        if not tenant_id:
            diagnostics.append("\n❌ **ERROR:** Could not determine tenant ID")
            return "\n".join(diagnostics)
        
        diagnostics.append("\n**Testing Graph API call...**")
        
        # Try the Graph API call
        try:
            messages = await get_channel_messages_rsc(
                team_id=team_id,
                channel_id=channel_id,
                top=1,
                tenant_id=tenant_id
            )
            
            if messages:
                diagnostics.append(f"✅ **SUCCESS!** Retrieved {len(messages)} message(s)")
                diagnostics.append("\nRSC is working correctly!")
            else:
                diagnostics.append("⚠️ **No messages returned** (could be empty channel or permission issue)")
                diagnostics.append("\n**Check logs for detailed error message**")
                diagnostics.append("\n**Common fixes:**")
                diagnostics.append("1. Ensure the app is installed in THIS specific team")
                diagnostics.append("2. Ensure RSC permissions were consented during install")
                diagnostics.append("3. Verify `webApplicationInfo.id` matches GRAPH_APP_ID")
                diagnostics.append("4. Check tenant RSC policy allows these permissions")
                
        except Exception as e:
            diagnostics.append(f"❌ **ERROR:** {str(e)}")
            logger.error(f"RSC test error: {e}", exc_info=True)
        
        return "\n".join(diagnostics)

    async def _handle_team_cache(self, context: TurnContext) -> str:
        """
        Handle /teamcache command - show team mapping cache status.
        
        This helps diagnose if the aadGroupId mapping is being cached correctly.
        """
        cache_stats = team_mapping_cache.get_stats()
        
        # Get current team info from this message
        team_id, channel_id = extract_team_channel_ids(context.activity)
        conv_type = get_conversation_type_from_activity(context.activity)
        
        # Get thread ID for lookup
        thread_id = None
        if hasattr(context.activity, 'channel_data') and context.activity.channel_data:
            channel_data = context.activity.channel_data
            if isinstance(channel_data, dict):
                thread_id = channel_data.get('teamsTeamId')
                if not thread_id:
                    team_data = channel_data.get('team', {})
                    if isinstance(team_data, dict):
                        thread_id = team_data.get('id')
        
        # Check if this team is in cache
        cached_info = None
        if thread_id:
            cached_info = team_mapping_cache.get_mapping_info(thread_id)
        
        result = ["**🗂️ Team Mapping Cache Status**\n"]
        result.append(f"**Cached Teams:** {cache_stats['cached_teams']}")
        
        if cache_stats['cached_teams'] > 0:
            result.append("\n**Cached Mappings:**")
            for tid, gid in cache_stats['mappings'].items():
                result.append(f"• `{tid}` → `{gid}`")
        
        result.append(f"\n**Current Context:**")
        result.append(f"• **Conversation Type:** {conv_type}")
        result.append(f"• **Team ID (GUID):** `{team_id or 'Not found'}`")
        result.append(f"• **Channel ID:** `{channel_id[:30] + '...' if channel_id and len(channel_id) > 30 else channel_id or 'N/A'}`")
        result.append(f"• **Thread ID:** `{thread_id[:30] + '...' if thread_id and len(thread_id) > 30 else thread_id or 'N/A'}`")
        
        if cached_info:
            result.append(f"\n✅ **This team IS in cache:**")
            result.append(f"• AAD Group ID: `{cached_info.get('aad_group_id')}`")
            result.append(f"• Team Name: {cached_info.get('team_name') or 'Unknown'}")
            result.append(f"• Cached At: {cached_info.get('cached_at')}")
        elif thread_id and conv_type == "channel":
            result.append(f"\n⚠️ **This team is NOT in cache.**")
            result.append("The bot may need to be removed and re-added to this team to cache the mapping.")
        
        return "\n".join(result)

    async def _handle_whois(self, context: TurnContext, user_id: str) -> str:
        """
        Handle /whois command - look up a user by ID.
        
        Uses application permissions (no user sign-in required).
        """
        try:
            # Get tenant from activity
            tenant_id = None
            if hasattr(context.activity, 'channel_data') and context.activity.channel_data:
                channel_data = context.activity.channel_data
                if isinstance(channel_data, dict):
                    tenant_data = channel_data.get('tenant', {})
                    if isinstance(tenant_data, dict):
                        tenant_id = tenant_data.get('id')
            
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

    async def _handle_default(self, message: str, user_context: UserContext) -> str:
        """Handle default message - echo back the message."""
        ctx = user_context.to_dict()

        response = f"You said: **{message}**"

        if ctx['is_cross_tenant'] and user_context.user_tenant_id:
            response += (
                f"\n\n_This is a cross-tenant message. "
                f"You are from {user_context.user_tenant_id[:20]}..._"
            )

        return response

    def _build_welcome_message(self, user_context: UserContext) -> str:
        """Build the welcome message for new users."""
        ctx = user_context.to_dict()

        welcome = f"""
👋 **Welcome, {ctx['user_name']}!**

I'm a cross-tenant Teams bot powered by User-Assigned Managed Identity (UAMI).
No secrets or passwords are needed for authentication.

**Available commands:**
• `/help` - Get command list
• `/info` - See your information
• `/status` - Check bot status
• `/context` - View conversation context
• `/echo [text]` - Echo back text

Or just send a message and I'll respond!
"""

        if ctx['is_cross_tenant'] and user_context.user_tenant_id:
            welcome += (
                f"\n📡 _Note: You are communicating across tenants. "
                f"Your tenant: {user_context.user_tenant_id[:20]}..._"
            )

        return welcome.strip()

    def _log_message_received(self, user_context: UserContext):
        """Log incoming message details for debugging."""
        ctx = user_context.to_dict()
        cross_tenant_info = (
            "CROSS-TENANT"
            if ctx['is_cross_tenant']
            else "SAME-TENANT"
        )

        logger.info(
            f"Message from {ctx['user_name']} | "
            f"Tenant: {cross_tenant_info} | "
            f"Conversation: {ctx['conversation_id'][:20] if ctx['conversation_id'] else 'unknown'}..."
        )


# Initialize configuration and bot
config = BotConfig()
config.log_config()
bot = CrossTenantBot(config)

# Create authentication configuration early (needed for adapter)
# For UserAssignedMSI bots: AZURE_CLIENT_ID and MICROSOFT_APP_ID should be THE SAME
# Both should be the UAMI Client ID
if config.azure_client_id != config.microsoft_app_id:
    logger.warning("⚠️  AZURE_CLIENT_ID != MICROSOFT_APP_ID")
    logger.warning(f"   AZURE_CLIENT_ID: {config.azure_client_id}")
    logger.warning(f"   MICROSOFT_APP_ID: {config.microsoft_app_id}")
    logger.warning("   For UserAssignedMSI bots, these should be the SAME (UAMI Client ID)!")

# Use AZURE_CLIENT_ID (UAMI) as the primary ID for UserAssignedMSI
bot_app_id = config.azure_client_id or config.microsoft_app_id or ""

auth_config = AgentAuthConfiguration(
    client_id=bot_app_id,  # UAMI Client ID = Bot App ID for UserAssignedMSI
    tenant_id=config.azure_tenant_id or "",
    auth_type=AuthTypes.user_managed_identity,
    connection_name="SERVICE_CONNECTION"  # Must match the key in MsalConnectionManager
)
logger.info("=" * 80)
logger.info("UserAssignedMSI CONFIGURATION:")
logger.info(f"  Bot/UAMI App ID: {bot_app_id}")
logger.info(f"  Tenant ID: {config.azure_tenant_id}")
logger.info("=" * 80)

# Skip UAMI test when running locally (no managed identity available)
if os.getenv("WEBSITE_INSTANCE_ID") or os.getenv("CONTAINER_APP_NAME"):
    # Running in Azure - test UAMI
    try:
        from azure.identity import DefaultAzureCredential
        test_cred = DefaultAzureCredential(
            managed_identity_client_id=config.azure_client_id
        )
        test_token = test_cred.get_token("https://graph.microsoft.com/.default")
        logger.info("✅ UAMI is accessible and working")
    except Exception as e:
        logger.error(f"❌ UAMI is NOT accessible: {e}")
        logger.error("UAMI might not be assigned to Container App!")
        raise
else:
    logger.info("⚠️ Running locally - skipping UAMI test (no managed identity available)")

# Create connection manager for CloudAdapter
# For UserAssignedMSI: The UAMI Client ID IS the Bot App ID - they are the same
try:
    connection_manager = MsalConnectionManager(
        connections_configurations={
            "SERVICE_CONNECTION": {
                "client_id": bot_app_id,  # UAMI Client ID = Bot App ID
                "tenant_id": config.azure_tenant_id or "",
                "auth_type": AuthTypes.user_managed_identity,
                "connection_name": "SERVICE_CONNECTION",
            }
        }
    )
    logger.info("✅ Connection manager created with UserManagedIdentity auth")
    logger.info(f"   App ID: {bot_app_id}")
    logger.info(f"   Tenant ID: {config.azure_tenant_id}")

except Exception as e:
    logger.error(f"❌ CRITICAL: Failed to create MsalConnectionManager: {e}", exc_info=True)
    logger.error("❌ Cannot proceed without UAMI authentication - bot will not work correctly")
    raise RuntimeError(f"MsalConnectionManager initialization failed: {e}") from e

# Create adapter with connection manager - no fallback
try:
    adapter = CloudAdapter(connection_manager=connection_manager)
    logger.info("✅ CloudAdapter created with connection manager")
except Exception as e:
    logger.error(f"❌ CRITICAL: Failed to create CloudAdapter: {e}", exc_info=True)
    raise RuntimeError(f"CloudAdapter initialization failed: {e}") from e

# Create storage for state management
STORAGE = MemoryStorage()

# Load config from environment for AgentApplication
agents_sdk_config = load_configuration_from_env(dict(os.environ))

# Create the Agent Application (no Authorization needed - using RSC instead)
AGENT_APP = AgentApplication[TurnState](
    storage=STORAGE,
    adapter=adapter,
    **agents_sdk_config
)
logger.info("Agent application created with RSC support (no user OAuth required)")

# ============================================================================
# Context handlers (No OAuth required - uses RSC and conversation state)
# ============================================================================

@AGENT_APP.message(re.compile(r"^/context$", re.IGNORECASE))
async def handle_context(context: TurnContext, state: TurnState):
    """
    Handle /context command - shows conversation context.
    Uses in-memory state for 1:1/group chats, Graph API for channels.
    No user sign-in required.
    """
    user_context = UserContext(context)
    response = await bot._handle_context(context, user_context)
    await context.send_activity(response)


@AGENT_APP.message(re.compile(r"^/contextinfo$", re.IGNORECASE))
async def handle_context_info(context: TurnContext, state: TurnState):
    """Handle /contextinfo command - shows conversation state info."""
    response = await bot._handle_context_info(context)
    await context.send_activity(response)


@AGENT_APP.message(re.compile(r"^/whois\s+(.+)$", re.IGNORECASE))
async def handle_whois(context: TurnContext, state: TurnState):
    """Handle /whois command - look up a user by ID using app permissions."""
    message = context.activity.text or ""
    user_id = message[7:].strip() if message.lower().startswith("/whois ") else ""
    
    if user_id:
        response = await bot._handle_whois(context, user_id)
    else:
        response = "Usage: `/whois <user-aad-object-id>`"
    
    await context.send_activity(response)


# ============================================================================
# Regular handlers (no OAuth required)
# ============================================================================

# Help command handler
async def _help_handler(context: TurnContext, state: TurnState):
    """Handle /help command."""
    await bot.on_message_activity(context, state)


# Register handlers using the SDK patterns
AGENT_APP.conversation_update(ConversationUpdateTypes.MEMBERS_ADDED)(bot.on_members_added)
AGENT_APP.message("/help")(_help_handler)
AGENT_APP.message("/info")(_help_handler)
AGENT_APP.message("/status")(_help_handler)


@AGENT_APP.activity("message")
async def on_message(context: TurnContext, state: TurnState):
    """Handle all incoming messages."""
    await bot.on_message_activity(context, state)


# Main entry point
if __name__ == "__main__":
    try:
        configure_logging()
        logger.info("Starting cross-tenant bot with RSC support...")
        logger.info("Bot will be available at http://localhost:3978/api/messages")
        
        # Log configuration
        logger.info("=" * 80)
        logger.info("CONFIGURATION:")
        logger.info(f"  UAMI Client ID: {config.azure_client_id}")
        logger.info(f"  Graph App ID: {os.getenv('GRAPH_APP_ID', 'Not set')}")
        logger.info(f"  Key Vault: {os.getenv('KEY_VAULT_NAME', 'Not set')}")
        logger.info("=" * 80)
        
        start_server(AGENT_APP, auth_config)
    except Exception as error:
        logger.error(f"Failed to start bot: {error}", exc_info=True)
        raise error
