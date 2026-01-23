# App Module

Core bot implementation using Microsoft 365 Agents SDK.

## Files

| File | Description |
|------|-------------|
| `__main__.py` | Bot entry point, message handlers, command routing |
| `conversation_state.py` | In-memory conversation history for 1:1/group chats |
| `graph_rsc_client.py` | Microsoft Graph API client with RSC support |
| `log_config.py` | Logging configuration |
| `start_server.py` | aiohttp server initialization |
| `trace_config.py` | Application Insights telemetry (optional) |

## Key Components

### CrossTenantBot
Main bot class handling all message types and commands.

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
```

See the main [README.md](../README.md) for full setup instructions.
