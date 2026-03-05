"""
Foundry Agent Client using Microsoft Agent Framework.

This module provides a client for interacting with Azure AI Foundry agents
built with Microsoft Agent Framework, with:
- Foundry-native observability/tracing
- Web search tool for real-time information
- Foundry IQ knowledge base via MCP for enterprise data
- Persistent agent (not recreated each session)
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

from agent_framework import ChatAgent, HostedWebSearchTool, HostedMCPTool
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, AzureCliCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry.trace import SpanKind
from opentelemetry import trace

logger = logging.getLogger("cross-tenant-bot.agents")


@dataclass
class AgentResponse:
    """Response from the Foundry agent."""
    
    content: str
    conversation_id: str
    status: str
    trace_id: Optional[str] = None
    error: Optional[str] = None
    
    @property
    def is_success(self) -> bool:
        return self.status == "completed" and self.error is None


# Agent system instructions
AGENT_INSTRUCTIONS = """You are a Microsoft Expert Assistant - a Teams bot that ONLY answers questions about Microsoft.

SCOPE - WHAT YOU CAN ANSWER:
- Microsoft products (Windows, Office, Azure, Microsoft 365, Teams, etc.)
- Microsoft services and platforms
- Microsoft company information (leadership, news, earnings, history)
- Microsoft technologies (Azure AI, .NET, Visual Studio, GitHub, etc.)
- Microsoft certifications and learning paths
- Microsoft pricing and licensing

OUT OF SCOPE - POLITELY DECLINE:
- Questions about other companies (Apple, Google, Amazon, etc.)
- Non-Microsoft topics (weather, sports, recipes, general knowledge)
- Personal advice, entertainment, or unrelated topics

HOW TO RESPOND TO OUT-OF-SCOPE QUESTIONS:
Say: "I'm a Microsoft Expert Assistant and can only help with Microsoft-related questions. Please ask me about Microsoft products, services, Azure, Windows, Office, or other Microsoft topics."

CRITICAL RULES:
1. ALWAYS use web_search to get the latest Microsoft information
2. Be accurate - use search results, don't guess
3. If you can't find information, say so clearly
4. Keep responses concise and helpful
5. Format responses for Teams (use markdown when helpful)

You are operating in Microsoft Teams with users from various tenants.
"""


class FoundryAgentClient:
    """
    Client for interacting with Azure AI Foundry agents using Microsoft Agent Framework.
    
    Features:
    - Persistent agent registration in Foundry
    - Foundry-native observability and tracing
    - Bing grounding for web search
    - Azure AI Search for knowledge base queries
    """
    
    def __init__(
        self,
        project_endpoint: Optional[str] = None,
        model_deployment_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        managed_identity_client_id: Optional[str] = None,
    ):
        """
        Initialize the Foundry Agent client.
        
        Args:
            project_endpoint: Azure AI Foundry project endpoint URL
            model_deployment_name: Name of the model deployment to use
            agent_name: Name of the agent
            managed_identity_client_id: UAMI client ID for authentication
        """
        # Support both new normalized names and legacy names for backward compatibility
        self.project_endpoint = project_endpoint or os.getenv("AZURE_AI_ENDPOINT") or os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        self.model_deployment_name = model_deployment_name or os.getenv("AZURE_AI_MODEL") or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4o")
        self.agent_name = agent_name or os.getenv("AZURE_AI_AGENT_NAME") or os.getenv("FOUNDRY_AGENT_NAME", "teams-bot-agent")
        self.managed_identity_client_id = managed_identity_client_id or os.getenv("AZURE_CLIENT_ID")
        
        # Agent ID for Foundry registration (lowercase alphanumeric with hyphens)
        self.agent_id = self.agent_name.lower().replace("_", "-").replace(" ", "-")
        
        # Cache for conversation threads (Teams conversation ID -> thread)
        self._thread_cache: Dict[str, Any] = {}
        
        # Cached agent instance (persistent across requests)
        self._agent: Optional[ChatAgent] = None
        self._client: Optional[AzureOpenAIResponsesClient] = None
        
        # Observability state
        self._observability_configured = False
    
    @property
    def is_configured(self) -> bool:
        """Check if the client is properly configured."""
        return bool(self.project_endpoint)
    
    def _get_credential(self):
        """Get the appropriate async Azure credential.
        
        Uses AzureCliCredential when LOCAL_DEBUG=true for local development (uses `az login` session),
        otherwise uses ManagedIdentityCredential when AZURE_CLIENT_ID is set (for ACA).
        """
        # Check for local development mode
        local_debug = os.getenv("LOCAL_DEBUG", "").lower() in ("true", "1", "yes")
        
        if local_debug:
            # Use AzureCliCredential directly - it uses the `az login` session
            # This avoids issues with VS Code/shared token cache using wrong tenant
            logger.info("LOCAL_DEBUG enabled - using AzureCliCredential (az login session)")
            return AzureCliCredential()
        elif self.managed_identity_client_id:
            logger.info("Using ManagedIdentityCredential with UAMI")
            return ManagedIdentityCredential(client_id=self.managed_identity_client_id)
        else:
            return DefaultAzureCredential()
    
    async def _setup_observability(self):
        """
        Setup observability with Application Insights.
        
        Uses connection string from environment variable.
        """
        if self._observability_configured:
            return
        
        try:
            conn_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
            
            if conn_string:
                configure_azure_monitor(
                    connection_string=conn_string,
                    enable_live_metrics=True,
                )
                self._observability_configured = True
                logger.info("Azure Monitor observability configured")
            else:
                logger.warning("APPLICATIONINSIGHTS_CONNECTION_STRING not set - telemetry disabled")
                            
        except Exception as e:
            logger.error(f"Error setting up observability: {e}")
    
    def _build_tools(self) -> list:
        """
        Build the list of tools for the agent.
        
        Returns:
            List of tool instances
        """
        tools = []
        
        # Add web search tool for real-time information
        try:
            web_search = HostedWebSearchTool()
            tools.append(web_search)
            logger.info("Added web search tool")
        except Exception as e:
            logger.warning(f"Could not add web search tool: {e}")
        
        # Add Foundry IQ knowledge base via MCP tool
        # NOTE: MCP knowledge base requires proper Azure AI Foundry project connection setup
        # The HostedMCPTool authentication is handled through the Foundry project, not direct headers
        # For now, disabled until proper Foundry IQ connection is configured
        # See: https://learn.microsoft.com/azure/ai-foundry/agents/how-to/foundry-iq-connect
        search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT") or os.getenv("FOUNDRY_SEARCH_ENDPOINT")
        kb_name = os.getenv("AZURE_SEARCH_INDEX_NAME") or os.getenv("FOUNDRY_KNOWLEDGE_BASE_NAME")
        
        if search_endpoint and kb_name:
            logger.info(f"Knowledge base configured but MCP tool disabled pending Foundry IQ connection setup: {kb_name}")
            # TODO: Enable once Foundry IQ project connection is configured
            # try:
            #     mcp_endpoint = f"{search_endpoint}/knowledgebases/{kb_name}/mcp?api-version=2025-11-01-preview"
            #     mcp_tool = HostedMCPTool(
            #         name="knowledge_base",
            #         url=mcp_endpoint,
            #         approval_mode="never_require",
            #     )
            #     tools.append(mcp_tool)
            #     logger.info(f"Added Foundry IQ knowledge base tool: {kb_name}")
            # except Exception as e:
            #     logger.warning(f"Could not add Foundry IQ MCP tool: {e}")
        
        return tools
    
    async def _get_or_create_agent(self) -> ChatAgent:
        """
        Get existing agent or create a new one.
        
        The agent is cached and reused across sessions to avoid
        recreating it on every request.
        
        Returns:
            The ChatAgent instance
        """
        if self._agent is not None:
            return self._agent
        
        # Setup observability first
        await self._setup_observability()
        
        # Create the Azure OpenAI Responses client
        credential = self._get_credential()
        self._client = AzureOpenAIResponsesClient(
            credential=credential,
            endpoint=self.project_endpoint,
            deployment_name=self.model_deployment_name,
        )
        
        # Build tools
        tools = self._build_tools()
        
        # Create the agent using the client's create_agent method
        self._agent = self._client.create_agent(
            name=self.agent_name,
            instructions=AGENT_INSTRUCTIONS,
            tools=tools if tools else None,
        )
        
        logger.info(f"Agent created: {self.agent_name}")
        return self._agent
    
    async def chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        user_name: Optional[str] = None,
        additional_context: Optional[str] = None
    ) -> AgentResponse:
        """
        Send a message to the Foundry agent and get a response.
        
        Args:
            message: The user's message
            conversation_id: Optional conversation ID for multi-turn chat
            user_name: Optional user name for context
            additional_context: Optional additional context to include
            
        Returns:
            AgentResponse with the agent's reply
        """
        if not self.is_configured:
            logger.warning("Foundry Agent client not configured - AZURE_AI_ENDPOINT not set")
            return AgentResponse(
                content="I'm sorry, but I'm not fully configured to respond right now. Please contact an administrator.",
                conversation_id=conversation_id or "",
                status="error",
                error="Foundry client not configured - AZURE_AI_ENDPOINT not set"
            )
        
        try:
            # Get or create agent
            agent = await self._get_or_create_agent()
            
            # Get tracer for custom spans
            tracer = trace.get_tracer(__name__)
            
            # Build the message with optional context
            full_message = message
            if user_name:
                full_message = f"[User: {user_name}]\n{message}"
            if additional_context:
                full_message = f"{full_message}\n\n[Context: {additional_context}]"
            
            # Get or create thread for multi-turn conversation
            thread = self._get_or_create_thread(conversation_id)
            
            # Run the agent with tracing
            with tracer.start_as_current_span(
                "Teams Bot Agent Chat",
                kind=SpanKind.CLIENT
            ) as span:
                from opentelemetry.trace.span import format_trace_id
                trace_id = format_trace_id(span.get_span_context().trace_id)
                
                span.set_attribute("agent.id", self.agent_id)
                span.set_attribute("agent.name", self.agent_name)
                span.set_attribute("conversation.id", conversation_id or "new")
                span.set_attribute("user.name", user_name or "unknown")
                
                # Log the user message (truncate if > 8KB to avoid span limits)
                span.set_attribute("user.message", message[:8000] if len(message) > 8000 else message)
                span.set_attribute("message.length", len(message))
                
                # Run the agent with thread for multi-turn conversation (streaming)
                response_text = ""
                async for update in agent.run_stream(full_message, thread=thread):
                    if update.text:
                        response_text += update.text
                
                if not response_text:
                    response_text = "I processed your request but didn't generate a response. Please try again."
                
                # Log the response (truncate if > 8KB to avoid span limits)
                span.set_attribute("agent.response", response_text[:8000] if len(response_text) > 8000 else response_text)
                span.set_attribute("response.length", len(response_text))
                
                logger.info(f"Agent response generated. Trace ID: {trace_id}")
                
                return AgentResponse(
                    content=response_text,
                    conversation_id=conversation_id or "",
                    status="completed",
                    trace_id=trace_id
                )
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error in Foundry agent chat: {e}", exc_info=True)
            
            return AgentResponse(
                content="I'm sorry, I encountered an unexpected error. Please try again later.",
                conversation_id=conversation_id or "",
                status="error",
                error=error_msg
            )
    
    def _get_or_create_thread(self, conversation_id: Optional[str]):
        """
        Get existing thread for conversation or create a new one.
        
        Args:
            conversation_id: The Teams conversation ID
            
        Returns:
            An AgentThread instance for multi-turn conversation
        """
        if conversation_id and conversation_id in self._thread_cache:
            return self._thread_cache[conversation_id]
        
        # Create new thread
        agent = self._agent
        if agent is not None:
            thread = agent.get_new_thread()
            if conversation_id:
                self._thread_cache[conversation_id] = thread
            return thread
        
        return None
    
    def clear_session(self, conversation_id: str) -> bool:
        """
        Clear the cached thread for a conversation.
        
        Args:
            conversation_id: The Teams conversation ID
            
        Returns:
            True if thread was cleared, False if not found
        """
        if conversation_id in self._thread_cache:
            del self._thread_cache[conversation_id]
            return True
        return False
    
    def cleanup(self):
        """Clean up resources (call on shutdown)."""
        self._thread_cache.clear()
        self._agent = None
        self._client = None
        logger.info("Foundry agent client cleaned up")


# Module-level singleton instance
_agent_client: Optional[FoundryAgentClient] = None


def get_agent_client() -> FoundryAgentClient:
    """
    Get the singleton Foundry agent client instance.
    
    Returns:
        The FoundryAgentClient instance
    """
    global _agent_client
    
    if _agent_client is None:
        _agent_client = FoundryAgentClient()
    
    return _agent_client


async def chat_with_agent(
    message: str,
    conversation_id: Optional[str] = None,
    user_name: Optional[str] = None,
    context: Optional[str] = None
) -> str:
    """
    Convenience function to chat with the Foundry agent.
    
    Args:
        message: The user's message
        conversation_id: Optional conversation ID for multi-turn context
        user_name: Optional user name
        context: Optional additional context
        
    Returns:
        The agent's response text
    """
    client = get_agent_client()
    response = await client.chat(
        message=message,
        conversation_id=conversation_id,
        user_name=user_name,
        additional_context=context
    )
    return response.content
