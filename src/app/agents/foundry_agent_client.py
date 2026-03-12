"""
Foundry Agent Client using Microsoft Agent Framework.

Thin client that orchestrates multi-agent workflows via HandoffBuilder.
Agent definitions live in separate modules (triage_agent, web_agent, license_agent).
The orchestrator module composes them into a handoff workflow.
"""

import os
import logging
from typing import Optional, Any
from dataclasses import dataclass

from agent_framework import AgentResponseUpdate, Message
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, AzureCliCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry.trace import SpanKind
from opentelemetry import trace

from app.agents.orchestrator import create_agents, create_workflow

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


class FoundryAgentClient:
    """
    Client for interacting with Azure AI Foundry agents using Microsoft Agent Framework.

    Uses HandoffBuilder to orchestrate a triage agent, web agent, and license agent.
    The triage agent routes questions to the appropriate specialist.
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



        # Cached agent instances (created once, reused across workflows)
        self._agents_created = False
        self._triage = None
        self._web_agent = None
        self._license_agent = None
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
                try:
                    from agent_framework.observability import configure_otel_providers
                    configure_otel_providers(
                        vs_code_extension_port=4317,
                        enable_sensitive_data=True
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

    async def _ensure_agents_created(self):
        """Create all agents once (lazy init). Agents are reused across workflows."""
        if self._agents_created:
            return

        await self._setup_observability()

        credential = self._get_credential()
        self._client = AzureOpenAIResponsesClient(
            credential=credential,
            endpoint=self.project_endpoint,
            deployment_name=self.model_deployment_name,
        )

        self._triage, self._web_agent, self._license_agent = create_agents(
            self._client, credential
        )
        self._agents_created = True
        logger.info(f"Multi-agent orchestration ready: {self.agent_name}")

    def _create_workflow(self):
        """Create a fresh workflow for each message.

        A new workflow is needed per message because the HandoffBuilder workflow
        accumulates internal state (tool calls, conversation history) that becomes
        stale and causes 'No tool output found' errors on subsequent turns.
        Agents are reused across workflows (created once, cached on self).
        """
        return create_workflow(self._triage, self._web_agent, self._license_agent)

    def _build_chat_messages(
        self,
        message: str,
        conversation_id: Optional[str],
        user_name: Optional[str],
        additional_context: Optional[str],
    ) -> list:
        """Build a Message list from conversation history for multi-turn context.

        Retrieves prior turns from ConversationStateManager and converts them
        to Message objects (user -> role="user", bot -> role="assistant").
        The current user message (with optional enrichment) is appended last.

        This gives the triage agent full conversational context while still
        using a fresh workflow per message (no stale tool-call state).
        """
        from app.conversation_state import conversation_manager

        messages: list[Message] = []

        if conversation_id:
            conversation = conversation_manager.get_conversation(conversation_id)
            if conversation:
                stored = conversation.get_messages()
                # Exclude the last message — it's the current user message
                # (already added by __main__.py before calling chat)
                prior = stored[:-1] if stored else []
                for msg in prior:
                    role = "assistant" if msg.is_from_bot else "user"
                    messages.append(Message(role=role, text=msg.text))

        # Build current message with optional enrichment
        current_text = message
        if user_name:
            current_text = f"[User: {user_name}]\n{current_text}"
        if additional_context:
            current_text = f"{current_text}\n\n[Context: {additional_context}]"

        messages.append(Message(role="user", text=current_text))

        logger.debug(f"Built {len(messages)} Messages ({len(messages) - 1} history + 1 current)")
        return messages

    async def chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        user_name: Optional[str] = None,
        additional_context: Optional[str] = None
    ) -> AgentResponse:
        """
        Send a message to the orchestrated agent workflow and get a response.

        The triage agent routes the question to the appropriate specialist
        (web agent or license agent) via HandoffBuilder.

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
            # Ensure agents are created (lazy init)
            await self._ensure_agents_created()

            # Get tracer for custom spans
            tracer = trace.get_tracer(__name__)

            # Build conversation history as Message list for multi-turn context
            chat_messages = self._build_chat_messages(
                message, conversation_id, user_name, additional_context
            )

            # Create a fresh workflow per message (avoids stale tool-call state)
            workflow = self._create_workflow()

            # Run the workflow with tracing
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
                span.set_attribute("user.message", message[:8000] if len(message) > 8000 else message)
                span.set_attribute("message.length", len(message))
                span.set_attribute("history.turns", len(chat_messages) - 1)

                result = await workflow.run(chat_messages)

                # Extract output from workflow result
                response_text = ""

                # First: check WorkflowOutputEvent outputs (specialist responses via handoff)
                outputs = result.get_outputs()
                for output in outputs:
                    if isinstance(output, AgentResponseUpdate) and output.text:
                        response_text += str(output.text)

                # Fallback: if coordinator responded directly (no handoff), its response
                # won't be in get_outputs(). Scan ALL events for any text-bearing data.
                if not response_text:
                    for event in result:
                        data = getattr(event, 'data', None)
                        if data is not None and hasattr(data, 'text') and data.text:
                            response_text = str(data.text)

                if not response_text:
                    response_text = "I processed your request but didn't generate a response. Please try again."

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

    def cleanup(self):
        """Clean up resources (call on shutdown)."""
        self._agents_created = False
        self._triage = None
        self._web_agent = None
        self._license_agent = None
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
