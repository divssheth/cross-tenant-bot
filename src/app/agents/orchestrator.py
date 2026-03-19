"""HandoffBuilder orchestration composing triage, web, and license agents."""

import logging
from typing import Optional

from agent_framework import Agent
from agent_framework.azure import AzureAIProjectAgentProvider, AzureOpenAIResponsesClient
from agent_framework.orchestrations import HandoffBuilder

from app.agents.triage_agent import create_triage_agent
from app.agents.web_agent import create_web_agent
from app.agents.license_agent import create_license_agent

logger = logging.getLogger("cross-tenant-bot.agents.orchestrator")


async def create_agents(
    client: AzureOpenAIResponsesClient,
) -> tuple[Agent, Agent, Optional[Agent], Optional[AzureAIProjectAgentProvider]]:
    """Create all specialist agent instances.

    Args:
        client: AzureOpenAIResponsesClient for creating local agents.

    Returns:
        Tuple of (triage_agent, web_agent, license_agent, license_provider).
        license_agent and license_provider may be None.
        The caller must keep license_provider alive for the agent's lifetime.
    """
    triage = create_triage_agent(client)
    web_agent = create_web_agent(client)
    license_agent, license_provider = await create_license_agent()

    agents = ["triage", "web_agent"]
    if license_agent:
        agents.append("license_agent")
    logger.info(f"Agents created: {', '.join(agents)}")
    return triage, web_agent, license_agent, license_provider


def _max_handoffs_termination(max_handoffs: int):
    """Return a termination condition that stops after *max_handoffs* routing steps."""
    counter = {"n": 0}

    def _check(messages) -> bool:
        counter["n"] += 1
        if counter["n"] > max_handoffs:
            logger.warning("Handoff limit (%d) reached — terminating workflow", max_handoffs)
            return True
        return False

    return _check


def create_workflow(triage: Agent, web_agent: Agent, license_agent: Optional[Agent] = None):
    """Build a HandoffBuilder workflow from pre-created agents.

    Creates a new workflow instance (stateful per conversation).
    The triage agent is the entry point and routes to specialists.
    Routing is one-way: triage → specialist. Specialists do not hand back.
    If license_agent is None, the workflow runs with triage + web_agent only.

    Args:
        triage: The triage/router agent.
        web_agent: The web search specialist agent.
        license_agent: The licensing specialist agent (optional).

    Returns:
        A Workflow instance ready for .run() calls.
    """
    participants = [triage, web_agent]
    triage_targets = [web_agent]

    if license_agent:
        participants.append(license_agent)
        triage_targets.append(license_agent)

    builder = (
        HandoffBuilder(
            name="ms-expert-orchestration",
            participants=participants,
            termination_condition=_max_handoffs_termination(6),
        )
        .with_start_agent(triage)
        .add_handoff(triage, triage_targets)
    )

    workflow = builder.build()

    logger.info(f"HandoffBuilder workflow created (license_agent: {'enabled' if license_agent else 'disabled'})")
    return workflow
