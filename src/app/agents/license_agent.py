"""License agent backed by a deployed Foundry agent via AzureAIAgentClient.

Instead of wrapping the deployed agent behind an @ai_function tool,
the Agent is backed directly by AzureAIAgentClient which natively
communicates with the deployed Foundry agent. The Agent Framework handles
response extraction, streaming, and tracing automatically.
"""

import os
import logging
from typing import Optional

from agent_framework import Agent
from agent_framework.azure import AzureAIAgentClient, AzureOpenAIResponsesClient
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential

logger = logging.getLogger("cross-tenant-bot.agents.license")


def _create_async_credential():
    """Create the appropriate async credential based on environment."""
    local_debug = os.getenv("LOCAL_DEBUG", "").lower() in ("true", "1", "yes")
    client_id = os.getenv("AZURE_CLIENT_ID")

    if local_debug:
        return AzureCliCredential()
    elif client_id:
        return ManagedIdentityCredential(client_id=client_id)
    else:
        return DefaultAzureCredential()


def create_license_agent(
    client: AzureOpenAIResponsesClient, credential
) -> Optional[Agent]:
    """Create the license agent backed directly by a deployed Foundry agent.

    Uses AzureAIAgentClient to connect to an existing deployed Foundry agent
    by name. The deployed agent's own instructions, tools, and knowledge base
    are used directly — no local wrapper or proxy needed.

    Args:
        client: AzureOpenAIResponsesClient (unused — license agent has its own client).
        credential: Azure credential (unused — async credential created internally).

    Returns:
        An Agent backed by the deployed Foundry agent, or None.
    """
    agent_name = os.getenv("AZURE_AI_LICENSE_AGENT_ID", "")
    if not agent_name:
        logger.warning(
            "AZURE_AI_LICENSE_AGENT_ID is not set. License agent disabled. "
            "Set it to the Foundry agent name (e.g. 'unified-knowledge-agent-1')."
        )
        return None

    endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
    if not endpoint:
        logger.warning(
            "AZURE_AI_PROJECT_ENDPOINT is not set. License agent disabled."
        )
        return None

    async_credential = _create_async_credential()

    azure_ai_agent_client = AzureAIAgentClient(
        agent_name=agent_name,
        credential=async_credential,
        project_endpoint=endpoint,
        model_deployment_name=os.getenv("AZURE_AI_MODEL", "gpt-4.1"),
    )

    logger.info(f"License agent configured with Foundry agent: {agent_name}")

    return Agent(
        azure_ai_agent_client,
        instructions="If this question was misrouted and is NOT about licensing, call handoff_to_triage to re-route.",
        name="license_agent",
        description="Handles Microsoft 365 licensing, subscription, and entitlement questions using a specialized knowledge base",
    )
