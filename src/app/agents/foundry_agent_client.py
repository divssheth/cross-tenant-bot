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

from agent_framework import ChatAgent, HostedWebSearchTool, MCPStreamableHTTPTool
from agent_framework._tools import ai_function
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


# Microsoft acronym database for the decoder tool
MICROSOFT_ACRONYMS = {
    # Azure & Cloud
    "ARM": ("Azure Resource Manager", "The deployment and management service for Azure that provides a management layer to create, update, and delete resources."),
    "AKS": ("Azure Kubernetes Service", "Managed Kubernetes container orchestration service in Azure."),
    "ACA": ("Azure Container Apps", "Serverless container platform for running microservices and containerized apps."),
    "ACR": ("Azure Container Registry", "Private Docker registry service for storing and managing container images."),
    "AAD": ("Azure Active Directory", "Cloud-based identity and access management service (now Microsoft Entra ID)."),
    "ASE": ("App Service Environment", "Fully isolated, dedicated environment for running App Service apps at high scale."),
    "AVD": ("Azure Virtual Desktop", "Desktop and app virtualization service running in the cloud."),
    "APIM": ("API Management", "Hybrid, multi-cloud management platform for APIs across all environments."),
    "RBAC": ("Role-Based Access Control", "Authorization system for managing access to Azure resources."),
    "SAS": ("Shared Access Signature", "URI that grants restricted access rights to Azure Storage resources."),
    "SKU": ("Stock Keeping Unit", "Defines the pricing tier and capabilities of Azure resources."),
    "VNET": ("Virtual Network", "Fundamental building block for private networks in Azure."),
    "NSG": ("Network Security Group", "Contains security rules that allow or deny network traffic."),
    "PaaS": ("Platform as a Service", "Cloud computing model where provider delivers hardware and software tools."),
    "IaaS": ("Infrastructure as a Service", "Cloud computing model providing virtualized computing resources."),
    "SaaS": ("Software as a Service", "Software licensing model where applications are accessed over the internet."),
    
    # Microsoft 365 & Productivity
    "M365": ("Microsoft 365", "Subscription service including Office apps, cloud services, and security."),
    "O365": ("Office 365", "Legacy name for cloud-based productivity suite (now part of Microsoft 365)."),
    "SPO": ("SharePoint Online", "Cloud-based collaboration and document management platform."),
    "EXO": ("Exchange Online", "Cloud-based email and calendaring service."),
    "ODfB": ("OneDrive for Business", "Enterprise file hosting and synchronization service."),
    "Teams": ("Microsoft Teams", "Collaboration platform combining chat, video, file storage, and app integration."),
    "PAM": ("Privileged Access Management", "Security solution for managing elevated access permissions."),
    "DLP": ("Data Loss Prevention", "Set of tools and processes to prevent data breaches and exfiltration."),
    
    # Development & DevOps
    "ADO": ("Azure DevOps", "Set of development tools for software teams including repos, pipelines, boards."),
    "CLI": ("Command Line Interface", "Text-based interface for interacting with software and operating systems."),
    "SDK": ("Software Development Kit", "Collection of tools for developing applications for specific platforms."),
    "API": ("Application Programming Interface", "Set of protocols for building and integrating application software."),
    "REST": ("Representational State Transfer", "Architectural style for designing networked applications."),
    "CI/CD": ("Continuous Integration/Continuous Deployment", "Practice of automating integration and deployment of code changes."),
    "IaC": ("Infrastructure as Code", "Managing infrastructure through code rather than manual processes."),
    "VS": ("Visual Studio", "Full-featured IDE for developing applications on Windows, web, cloud."),
    "VSC": ("Visual Studio Code", "Lightweight, cross-platform source code editor."),
    
    # AI & Data
    "AOAI": ("Azure OpenAI", "Azure service providing access to OpenAI's models including GPT-4."),
    "AML": ("Azure Machine Learning", "Cloud service for training, deploying, and managing ML models."),
    "ADF": ("Azure Data Factory", "Cloud-based data integration service for creating data-driven workflows."),
    "ADB": ("Azure Databricks", "Apache Spark-based analytics platform optimized for Azure."),
    "RAG": ("Retrieval-Augmented Generation", "AI technique combining retrieval with generation for grounded responses."),
    "LLM": ("Large Language Model", "AI model trained on vast text data for language understanding and generation."),
    "GPT": ("Generative Pre-trained Transformer", "Type of large language model architecture from OpenAI."),
    "NLP": ("Natural Language Processing", "AI field focused on interaction between computers and human language."),
    
    # Security & Identity
    "MFA": ("Multi-Factor Authentication", "Security process requiring multiple forms of verification."),
    "SSO": ("Single Sign-On", "Authentication scheme allowing access to multiple applications with one login."),
    "MSAL": ("Microsoft Authentication Library", "Library for authenticating users and acquiring tokens."),
    "SPN": ("Service Principal Name", "Identity used by services or applications to access Azure resources."),
    "UAMI": ("User-Assigned Managed Identity", "Azure identity that can be assigned to multiple resources."),
    "SAMI": ("System-Assigned Managed Identity", "Identity tied to a specific Azure resource's lifecycle."),
    "PIM": ("Privileged Identity Management", "Service for managing, controlling, and monitoring privileged access."),
    "CAP": ("Conditional Access Policy", "Policies that control access based on conditions like location or device."),
    
    # Copilot & AI Assistants
    "M365C": ("Microsoft 365 Copilot", "AI assistant integrated into Microsoft 365 apps."),
    "GHC": ("GitHub Copilot", "AI pair programmer that suggests code in your editor."),
    "MAF": ("Microsoft Agent Framework", "SDK for building AI agents with tools and multi-agent support."),
    "MCP": ("Model Context Protocol", "Protocol for providing context to AI models from external sources."),
}


@ai_function
def decode_microsoft_acronym(acronym: str) -> str:
    """
    Decode a Microsoft/Azure/tech acronym and explain what it means.
    
    Use this tool when users ask about Microsoft acronyms, abbreviations,
    or technical terms they don't understand.
    
    Args:
        acronym: The acronym to decode (e.g., "AKS", "RBAC", "M365")
    
    Returns:
        The full name and explanation of the acronym
    """
    # Normalize input
    acronym_upper = acronym.upper().strip()
    
    if acronym_upper in MICROSOFT_ACRONYMS:
        full_name, description = MICROSOFT_ACRONYMS[acronym_upper]
        return f"**{acronym_upper}** = {full_name}\n\n{description}"
    
    # Try partial match
    partial_matches = [
        (key, val) for key, val in MICROSOFT_ACRONYMS.items() 
        if acronym_upper in key or key in acronym_upper
    ]
    
    if partial_matches:
        results = [f"**{key}** = {val[0]}: {val[1]}" for key, val in partial_matches[:3]]
        return f"No exact match for '{acronym}'. Did you mean:\n\n" + "\n\n".join(results)
    
    return f"I don't have '{acronym}' in my acronym database. Try using web search to find its meaning, or it might not be a standard Microsoft term."


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

AVAILABLE TOOLS:
1. **decode_microsoft_acronym**: Instantly decode Microsoft/Azure acronyms (AKS, RBAC, M365, etc.)
   - Use this FIRST when users ask "what does X stand for?" or mention unknown acronyms
   - Fast and accurate for common Microsoft terminology
2. **web_search**: Search the web for current Microsoft news and pricing
   - Use for latest news, pricing, announcements
3. **microsoft_docs_search**: Search official Microsoft Learn documentation (via MCP)
   - Use for how-to guides, tutorials, technical docs, architecture info
   - PREFERRED for documentation questions - returns trusted official content
4. **microsoft_docs_fetch**: Fetch full content from a Microsoft Learn page (via MCP)
   - Use when you have a specific learn.microsoft.com URL to read
5. **microsoft_code_sample_search**: Find official Microsoft/Azure code samples (via MCP)
   - Use when users need code examples, can filter by language

CRITICAL RULES:
1. For acronym questions, use decode_microsoft_acronym first - it's fastest
2. For documentation/how-to questions, use microsoft_docs_search (MCP) - trusted source
3. For code examples, use microsoft_code_sample_search with language filter
4. For news/pricing/announcements, use web_search
5. Be accurate - use tool results, don't guess
6. If you can't find information, say so clearly
7. Format responses for Teams (use markdown when helpful)

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
        Setup observability for the agent.
        
        Checks if tracing is already configured via trace_config module.
        Only configures if not already done.
        """
        if self._observability_configured:
            return
        
        try:
            # Check if tracing was already configured at app startup
            from app.trace_config import is_telemetry_enabled
            if is_telemetry_enabled():
                self._observability_configured = True
                logger.info("Using existing telemetry configuration from trace_config")
                return
            
            local_debug = os.getenv("LOCAL_DEBUG", "").lower() in ("true", "1", "yes")
            
            if local_debug:
                # Use Agent Framework's built-in tracing for local development
                # Sends to AI Toolkit (OTLP on port 4317)
                try:
                    from agent_framework.observability import configure_otel_providers
                    configure_otel_providers(
                        vs_code_extension_port=4317,
                        enable_sensitive_data=True  # Capture prompts and completions
                    )
                    self._observability_configured = True
                    logger.info("Agent Framework tracing configured (AI Toolkit port 4317)")
                    return
                except ImportError:
                    logger.warning("agent_framework.observability not available")
            
            # Production: Use Azure Monitor
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
        
        # Add custom local tool for Microsoft acronym decoding
        # This creates visible spans in traces with inputs/outputs
        tools.append(decode_microsoft_acronym)
        logger.info("Added decode_microsoft_acronym tool")
        
        # Add web search tool for real-time information
        try:
            web_search = HostedWebSearchTool()
            tools.append(web_search)
            logger.info("Added web search tool")
        except Exception as e:
            logger.warning(f"Could not add web search tool: {e}")
        
        # Add official Microsoft Learn MCP Server for documentation access
        # This provides: microsoft_docs_search, microsoft_docs_fetch, microsoft_code_sample_search
        # See: https://github.com/MicrosoftDocs/mcp
        try:
            ms_learn_mcp = MCPStreamableHTTPTool(
                name="microsoft_learn",
                url="https://learn.microsoft.com/api/mcp",
                description="Official Microsoft Learn MCP Server - search/fetch Microsoft documentation and code samples",
                approval_mode="never_require",
                request_timeout=60,  # Documentation fetches can be slow
            )
            tools.append(ms_learn_mcp)
            logger.info("Added Microsoft Learn MCP tool (microsoft_docs_search, microsoft_docs_fetch, microsoft_code_sample_search)")
        except Exception as e:
            logger.warning(f"Could not add Microsoft Learn MCP tool: {e}")
        
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
