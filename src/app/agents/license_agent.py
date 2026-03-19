"""License agent backed by a persistent Foundry v2 agent.

Uses AzureAIProjectAgentProvider.get_agent() to retrieve an existing
persistent agent by name — no new agent instances are created on each
startup. The deployed agent's instructions, tools, and knowledge base
are used directly via the Azure AI Projects SDK (v2).
"""

import os
import logging
from typing import Optional

from agent_framework import Agent
from agent_framework.azure import AzureAIProjectAgentProvider
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


async def create_license_agent() -> tuple[Optional[Agent], Optional[AzureAIProjectAgentProvider]]:
    """Retrieve the license agent from Foundry v2 by name.

    Uses AzureAIProjectAgentProvider.get_agent() to fetch the existing
    persistent agent — no new agent instances (asst_*) are created.

    Returns:
        Tuple of (Agent, provider). Provider must be kept alive for the
        agent's lifetime. Both are None if config is missing.
    """
    agent_name = os.getenv("AZURE_AI_LICENSE_AGENT_ID", "")
    if not agent_name:
        logger.warning(
            "AZURE_AI_LICENSE_AGENT_ID is not set. License agent disabled. "
            "Set it to the Foundry agent name (e.g. 'unified-knowledge-agent-1')."
        )
        return None, None

    endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
    if not endpoint:
        logger.warning(
            "AZURE_AI_PROJECT_ENDPOINT is not set. License agent disabled."
        )
        return None, None

    async_credential = _create_async_credential()

    provider = AzureAIProjectAgentProvider(
        project_endpoint=endpoint,
        credential=async_credential,
    )

    agent = await provider.get_agent(name=agent_name)
    # Override name so HandoffBuilder generates 'handoff_to_license_agent'
    # matching the triage agent's routing instructions.
    agent.name = "license_agent"

    # Sanitize tool dicts: the Azure AI Projects SDK returns Model objects
    # (MCPToolRequireApproval, MCPToolFilter) inside tool dicts that aren't
    # JSON-serializable, causing the Agent Framework's observability layer
    # to crash.  Convert them to plain dicts.
    _sanitize_tool_dicts(agent.default_options.get("tools", []))

    logger.info("License agent retrieved from Foundry v2: %s (handoff name: %s)", agent_name, agent.name)

    return agent, provider


def _sanitize_tool_dicts(tools: list) -> None:
    """Convert any Azure SDK Model objects in tool dicts to plain dicts (in-place)."""
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        for key, value in list(tool.items()):
            if hasattr(value, "as_dict"):
                tool[key] = value.as_dict()
