"""
Agents module for Azure AI Foundry integration.
"""

from app.agents.foundry_agent_client import (
    FoundryAgentClient,
    AgentResponse,
    get_agent_client,
    chat_with_agent,
)

__all__ = [
    "FoundryAgentClient",
    "AgentResponse",
    "get_agent_client",
    "chat_with_agent",
]
