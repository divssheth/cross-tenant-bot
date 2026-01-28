# Cross-Tenant Teams Bot - Modular Architecture

This directory contains a **cookiecutter-style Teams bot** that you can easily customize.

## Directory Structure

```
app/
├── __main__.py              # Entry point (minimal)
├── config/                  # ✏️ CUSTOMIZE - Configuration
│   ├── settings.py          # All environment variables
│   └── prompts.py           # AI prompts and templates
│
├── core/                    # 🔒 DON'T MODIFY - Infrastructure
│   ├── conversation_state.py # State management
│   ├── user_context.py      # User information
│   └── utilities/
│       ├── rsc.py           # RSC Graph API utilities
│       └── teams_helpers.py # Teams-specific helpers
│
├── handlers/                # ✏️ CUSTOMIZE - Command handlers
│   ├── base.py              # CommandHandler interface
│   ├── registry.py          # Auto-discovery registry
│   ├── help_handler.py      # /help command
│   ├── info_handler.py      # /info command
│   ├── status_handler.py    # /status command
│   ├── context_handler.py   # /context commands
│   ├── ai_handler.py        # /ask, /summarize, default AI
│   ├── echo_handler.py      # /echo command
│   └── whois_handler.py     # /whois command (RSC)
│
└── agents/                  # ✏️ CUSTOMIZE - AI orchestration
    ├── base.py              # BaseAgent interface
    └── simple_agent.py      # Default implementation
```

## How to Customize

### 1. Add a New Command

Create a new file in `handlers/`:

```python
# handlers/my_handler.py
from app.handlers.base import CommandHandler
from app.handlers.registry import handler_registry

class MyCommandHandler(CommandHandler):
    @property
    def command(self) -> str:
        return "mycommand"  # Responds to /mycommand
    
    @property
    def description(self) -> str:
        return "Does something cool"
    
    @property
    def category(self) -> str:
        return "Custom"  # Grouping in /help
    
    async def handle(self, context, state, args):
        user = self.get_user_context(context)
        return f"Hello {user.user_name}! Args: {args}"

# Register the handler
handler_registry.register(MyCommandHandler())
```

Then add the import in `handlers/__init__.py`:
```python
from app.handlers.my_handler import MyCommandHandler
```

### 2. Replace the AI Agent

Create your own agent using any framework:

```python
# agents/langgraph_agent.py
from langgraph.graph import StateGraph
from app.agents.base import BaseAgent

class LangGraphAgent(BaseAgent):
    def __init__(self):
        self.graph = self._build_graph()
    
    async def process(self, user_message, context, history, conversation_type):
        result = await self.graph.ainvoke({
            "input": user_message,
            "context": context
        })
        return result["output"]
    
    async def summarize(self, messages, focus=None):
        # Your summarization logic
        return "Summary..."
    
    async def answer_question(self, question, messages):
        # Your Q&A logic
        return "Answer..."
```

Then update `agents/__init__.py`:
```python
def get_agent() -> BaseAgent:
    from app.agents.langgraph_agent import LangGraphAgent
    return LangGraphAgent()
```

### 3. Modify Configuration

Edit `config/settings.py` to add new environment variables:

```python
# Add to Settings class
MY_CUSTOM_SETTING: str = field(
    default_factory=lambda: os.getenv("MY_CUSTOM_SETTING", "default")
)
```

Edit `config/prompts.py` to customize AI behavior:

```python
AGENT_INSTRUCTIONS = """You are a specialized assistant for..."""
```

### 4. Use RSC Utilities in Handlers

```python
from app.core.utilities.rsc import (
    get_channel_messages_with_replies,
    is_rsc_enabled
)
from app.core.utilities.teams_helpers import (
    is_channel_conversation,
    get_conversation_context
)

class MyHandler(CommandHandler):
    async def handle(self, context, state, args):
        if is_rsc_enabled() and is_channel_conversation(context):
            messages = await get_conversation_context(context, max_messages=20)
            # Use messages...
```

## What NOT to Modify

The `core/` directory contains stable infrastructure:
- Bot adapter and authentication
- Message routing
- Conversation state management
- Utility functions

These components should not need modification for typical customizations.

## Feature Flags

Set these in your `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_RSC` | `false` | Enable RSC for channel message access |
| `ENABLE_AI` | `true` | Enable AI features |
| `LOCAL_DEBUG` | `false` | Use client_secret auth for local testing |

## Supported AI Frameworks

The `BaseAgent` interface is framework-agnostic. You can use:
- **Microsoft Agent Framework** (default)
- **LangGraph**
- **Semantic Kernel**
- **OpenAI directly**
- **Any other framework**

Just implement `process()`, `summarize()`, and `answer_question()`.
## Usage

```python
# Run the bot
python -m app
```

See the main [README.md](../README.md) for full setup instructions.
