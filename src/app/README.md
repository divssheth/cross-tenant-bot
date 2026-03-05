# App Module

Core bot implementation using Microsoft 365 Agents SDK with Azure AI Foundry agent integration.

## Directory Structure

```
app/
├── __init__.py
├── __main__.py           # Bot entry point, message handlers
├── conversation_state.py # In-memory conversation tracking
├── graph_rsc_client.py   # Graph API client with RSC support
├── log_config.py         # Structured logging configuration
├── start_server.py       # aiohttp server initialization
├── trace_config.py       # Azure Monitor telemetry
├── agents/               # AI agent clients
│   ├── __init__.py
│   └── foundry_agent_client.py  # Azure AI Foundry agent
└── eval/                 # Agent evaluation framework
    ├── __init__.py
    ├── evaluate_agent.py # Evaluation CLI and framework
    ├── test_data.json    # Test cases for evaluation
    └── results/          # Evaluation output
```

## Files

| File | Description |
|------|-------------|
| `__main__.py` | Bot entry point, message handlers, command routing |
| `conversation_state.py` | In-memory conversation history for 1:1/group chats |
| `graph_rsc_client.py` | Microsoft Graph API client with RSC support |
| `log_config.py` | Logging configuration with structured context |
| `start_server.py` | aiohttp server initialization |
| `trace_config.py` | Azure Monitor OpenTelemetry configuration |

## Submodules

### agents/
AI agent integration using Microsoft Agent Framework:
- **foundry_agent_client.py** - Azure AI Foundry agent with web search and knowledge base tools

### eval/
Comprehensive agent evaluation framework:
- **evaluate_agent.py** - CLI for running evaluations locally or logging to Foundry Portal
- **test_data.json** - Test cases organized by category (single-turn, multi-turn)

## Key Components

### CrossTenantBot
Main bot class handling all message types and commands.

### Foundry Agent Client
Connects to Azure AI Foundry using Microsoft Agent Framework:
- Persistent agent registration
- Web search tool (Bing grounding)
- Knowledge base integration (Azure AI Search)
- Foundry-native observability

### Graph RSC Client
Authenticates to Graph API using client credentials flow:
1. Retrieves client secret from Key Vault via UAMI
2. Gets token for target tenant
3. Calls Graph API with RSC permissions

### Conversation State
Stores recent messages in-memory for context in 1:1 and group chats.
For channels, uses Graph API to retrieve message history.

## Usage

```python
# Run the bot
python -m app

# Run evaluations
cd eval
python evaluate_agent.py --log-to-foundry
```

See the main [README.md](../../README.md) for full setup instructions.
