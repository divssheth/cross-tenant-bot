"""HandoffBuilder orchestration composing triage, web, and license agents."""

import logging
from typing import Optional

from agent_framework import ChatAgent, HandoffBuilder
from agent_framework.azure import AzureOpenAIResponsesClient

from app.agents.triage_agent import create_triage_agent
from app.agents.web_agent import create_web_agent
from app.agents.license_agent import create_license_agent

logger = logging.getLogger("cross-tenant-bot.agents.orchestrator")


def create_agents(client: AzureOpenAIResponsesClient, credential) -> tuple[ChatAgent, ChatAgent, Optional[ChatAgent]]:
    """Create all specialist agent instances.

    Args:
        client: AzureOpenAIResponsesClient for creating local agents.
        credential: Azure credential for the license agent's Foundry connection.

    Returns:
        Tuple of (triage_agent, web_agent, license_agent). license_agent may be None.
    """
    triage = create_triage_agent(client)
    web_agent = create_web_agent(client)
    license_agent = create_license_agent(client, credential)

    agents = ["triage", "web_agent"]
    if license_agent:
        agents.append("license_agent")
    logger.info(f"Agents created: {', '.join(agents)}")
    return triage, web_agent, license_agent


def create_workflow(triage: ChatAgent, web_agent: ChatAgent, license_agent: Optional[ChatAgent] = None):
    """Build a HandoffBuilder workflow from pre-created agents.

    Creates a new workflow instance (stateful per conversation).
    The triage agent is the entry point and routes to specialists.
    Specialists can hand back to triage if misrouted.
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
        )
        .set_coordinator(triage)
        .add_handoff(triage, triage_targets)
        .add_handoff(web_agent, [triage])
    )

    if license_agent:
        builder = builder.add_handoff(license_agent, [triage])

    workflow = (
        builder
        .with_interaction_mode("autonomous", autonomous_turn_limit=1)
        .build()
    )

    logger.info(f"HandoffBuilder workflow created (license_agent: {'enabled' if license_agent else 'disabled'})")
    return workflow
