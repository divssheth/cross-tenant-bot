"""License agent that proxies queries to a deployed Foundry agent via the new responses API."""

import os
import logging
from typing import Optional

from agent_framework import ChatAgent
from agent_framework._tools import ai_function
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential

logger = logging.getLogger("cross-tenant-bot.agents.license")

# Module-level async client cached after first successful init
_openai_client = None
_agent_name: Optional[str] = None


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


def _init_openai_client() -> bool:
    """Initialize the async OpenAI client from AIProjectClient. Returns True on success."""
    global _openai_client

    if _openai_client is not None:
        return True

    endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
    if not endpoint:
        return False

    credential = _create_async_credential()
    project_client = AIProjectClient(endpoint=endpoint, credential=credential)
    _openai_client = project_client.get_openai_client()
    return True


@ai_function
async def query_license_knowledge_base(question: str) -> str:
    """Query the Microsoft 365 licensing knowledge base for authoritative answers.

    Use this tool for ANY licensing, subscription, or entitlement question.
    The knowledge base contains official Microsoft licensing guides.

    Args:
        question: The licensing question to look up.

    Returns:
        The answer from the licensing knowledge base.
    """
    if _openai_client is None or _agent_name is None:
        return "License knowledge base is not available."

    try:
        response = await _openai_client.responses.create(
            model="gpt-4o",
            input=question,
            extra_body={
                "agent": {
                    "name": _agent_name,
                    "type": "agent_reference",
                }
            },
        )
        for item in response.output:
            if hasattr(item, "content"):
                for part in item.content:
                    if hasattr(part, "text"):
                        return part.text
        return "No answer found in the licensing knowledge base."
    except Exception as e:
        logger.error(f"Error querying license knowledge base: {e}", exc_info=True)
        return f"Error querying the licensing knowledge base: {e}"


LICENSE_AGENT_INSTRUCTIONS = """You are a Microsoft 365 Licensing Expert Agent.

You answer questions about Microsoft 365 licensing, subscriptions, and entitlements
using a specialized knowledge base.

ALWAYS use the query_license_knowledge_base tool to look up answers.
Do not guess or make up licensing information — use the tool for every question.

Format your answers clearly using markdown for Teams readability.
If the knowledge base doesn't have the answer, say so honestly.

If this question was misrouted and is NOT about licensing, call handoff_to_triage to re-route.
"""


def create_license_agent(
    client: AzureOpenAIResponsesClient, credential
) -> Optional[ChatAgent]:
    """Create the license agent backed by a deployed Foundry agent.

    Uses the new azure-ai-projects async responses API to query the deployed agent
    by name via the query_license_knowledge_base tool.

    Args:
        client: AzureOpenAIResponsesClient for creating the local ChatAgent.
        credential: Azure credential (unused — async credential created internally).

    Returns:
        A ChatAgent with a tool that proxies to the deployed Foundry agent, or None.
    """
    global _agent_name

    agent_name = os.getenv("AZURE_AI_LICENSE_AGENT_ID", "")
    if not agent_name:
        logger.warning(
            "AZURE_AI_LICENSE_AGENT_ID is not set. License agent disabled. "
            "Set it to the Foundry agent name (e.g. 'unified-knowledge-agent-1')."
        )
        return None

    if not _init_openai_client():
        logger.warning(
            "AZURE_AI_PROJECT_ENDPOINT is not set. License agent disabled."
        )
        return None

    _agent_name = agent_name
    logger.info(f"License agent configured with Foundry agent: {agent_name}")

    return client.create_agent(
        name="license_agent",
        instructions=LICENSE_AGENT_INSTRUCTIONS,
        tools=[query_license_knowledge_base],
        description="Handles Microsoft 365 licensing, subscription, and entitlement questions using a specialized knowledge base",
    )
