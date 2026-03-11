"""Web agent with search, documentation, and acronym tools."""

import os
import logging

from agent_framework import ChatAgent, HostedWebSearchTool, MCPStreamableHTTPTool
from agent_framework.azure import AzureOpenAIResponsesClient

from app.agents._acronyms import decode_microsoft_acronym

logger = logging.getLogger("cross-tenant-bot.agents.web")


WEB_AGENT_INSTRUCTIONS = """You are a Microsoft Expert Web Agent - you answer questions about Microsoft using web search and official documentation.

SCOPE - WHAT YOU CAN ANSWER:
- Microsoft products (Windows, Office, Azure, Microsoft 365, Teams, etc.)
- Microsoft services and platforms
- Microsoft company information (leadership, news, earnings, history)
- Microsoft technologies (Azure AI, .NET, Visual Studio, GitHub, etc.)
- Microsoft certifications and learning paths
- Microsoft pricing and general licensing info

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

TOOL USAGE:
1. For acronym questions, use decode_microsoft_acronym first - it's fastest
2. For documentation/how-to questions, use microsoft_docs_search (MCP) - trusted source
3. For code examples, use microsoft_code_sample_search with language filter
4. For news/pricing/announcements, use web_search
5. Be accurate - use tool results, don't guess
6. If you can't find information, say so clearly
7. Format responses for Teams (use markdown when helpful)

If this question was misrouted and is actually about licensing, call handoff_to_triage to re-route.

You are operating in Microsoft Teams with users from various tenants.
"""


def _build_tools() -> list:
    """Build the list of tools for the web agent."""
    tools = []

    tools.append(decode_microsoft_acronym)
    logger.info("Added decode_microsoft_acronym tool")

    try:
        web_search = HostedWebSearchTool()
        tools.append(web_search)
        logger.info("Added web search tool")
    except Exception as e:
        logger.warning(f"Could not add web search tool: {e}")

    try:
        ms_learn_mcp = MCPStreamableHTTPTool(
            name="microsoft_learn",
            url="https://learn.microsoft.com/api/mcp",
            description="Official Microsoft Learn MCP Server - search/fetch Microsoft documentation and code samples",
            approval_mode="never_require",
            request_timeout=60,
        )
        tools.append(ms_learn_mcp)
        logger.info("Added Microsoft Learn MCP tool")
    except Exception as e:
        logger.warning(f"Could not add Microsoft Learn MCP tool: {e}")

    return tools


def create_web_agent(client: AzureOpenAIResponsesClient) -> ChatAgent:
    """Create the web agent with search and documentation tools."""
    tools = _build_tools()
    return client.create_agent(
        name="web_agent",
        instructions=WEB_AGENT_INSTRUCTIONS,
        tools=tools if tools else None,
        description="Handles general Microsoft questions using web search, documentation, and acronym decoding",
    )
