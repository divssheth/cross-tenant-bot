# Cross-Tenant Multi-Agent Teams Bot

A Microsoft Teams bot combining **cross-tenant authentication** (UAMI + RSC) with **multi-agent orchestration** (Microsoft Agent Framework + Azure AI Foundry). The bot operates securely across organizational boundaries while routing user questions to specialized AI agents.

## Two Pillars

| Pillar | What It Solves |
|--------|---------------|
| **Cross-Tenant Auth** | Secure bot-to-tenant communication using UAMI for Bot Framework and RSC for Graph API — no secrets in code, no admin consent |
| **Multi-Agent Orchestration** | HandoffBuilder workflow routes questions through a triage agent to specialist agents (web search, licensing) with automatic tool use |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Your Tenant (Home)                                                     │
│                                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐                      │
│  │   UAMI   │─►│Key Vault │  │Multi-Tenant App  │                      │
│  │(Bot Auth)│  │(Secrets) │  │ (Graph API/RSC)  │                      │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘                      │
│       │              └─────────────────┤                                │
│       ▼                                ▼                                │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     Teams Bot Container                          │   │
│  │                                                                  │   │
│  │   User Message                                                   │   │
│  │       │                                                          │   │
│  │       ▼                                                          │   │
│  │   ┌─────────┐    ┌───────────┐    ┌───────────────┐             │   │
│  │   │ Triage  │───►│ Web Agent │    │ License Agent  │             │   │
│  │   │ (router)│    │ (search,  │    │ (Foundry       │             │   │
│  │   │         │───►│  MCP,     │    │  deployed,     │             │   │
│  │   │         │    │  acronyms)│    │  knowledge     │             │   │
│  │   └─────────┘    └───────────┘    │  base)         │             │   │
│  │       HandoffBuilder Workflow     └───────────────┘             │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              │ Bot Framework (cross-tenant routing)
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  External Tenant (Customer)                                             │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  Team with App Installed                                         │   │
│  │  ├─ RSC permissions granted at install (no admin consent)       │   │
│  │  ├─ Bot reads channel messages via Graph API                     │   │
│  │  └─ Per-team scoping (not tenant-wide access)                   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Multi-Agent Orchestration

The bot uses [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) with a **HandoffBuilder** workflow to route user questions to specialist agents.

### Agents

| Agent | Role | Tools |
|-------|------|-------|
| **Triage** | Router — analyzes intent and hands off to specialists | None (routing only) |
| **Web Agent** | General Microsoft questions | Web search (Bing), Microsoft Learn MCP, acronym decoder |
| **License Agent** | Microsoft 365 licensing questions | Foundry-deployed agent with knowledge base |

### How It Works

```python
from agent_framework.orchestrations import HandoffBuilder

# Local agents created via AzureOpenAIResponsesClient; Foundry agents retrieved via AzureAIProjectAgentProvider
workflow = (
    HandoffBuilder(
        name="ms-expert-orchestration",
        participants=[triage, web_agent, license_agent],
        termination_condition=_max_handoffs_termination(6),  # Safety net
    )
    .with_start_agent(triage)
    .add_handoff(triage, [web_agent, license_agent])  # One-way routing
    .build()
)

# Each user message goes through the workflow
result = await workflow.run(user_message)
```

- **Triage** receives every message, decides which specialist should handle it
- Routing is **one-way** (triage → specialists only) — specialists answer to the best of their ability or politely decline off-topic questions
- A `_max_handoffs_termination(6)` safety net prevents infinite loops
- The license agent is optional — if `AZURE_AI_LICENSE_AGENT_ID` is not set, the workflow runs with triage + web agent only

For deep-dive architecture details, see [docs/MULTI_AGENT_ORCHESTRATION.md](docs/MULTI_AGENT_ORCHESTRATION.md).

---

## Cross-Tenant Authentication

### Why UAMI + RSC?

Microsoft [deprecated multi-tenant bot creation](https://learn.microsoft.com/en-us/azure/bot-service/bot-service-quickstart-registration) after July 31, 2025. This architecture uses:

- **UAMI** for Bot Framework authentication (no secrets in code)
- **Multi-tenant app registration** solely for Graph API access (secret in Key Vault)
- **RSC** for per-team permissions (no tenant-wide admin consent)

### Key Benefits

| Benefit | Description |
|---------|-------------|
| **No Secrets in Code** | UAMI authenticates to Bot Framework and Key Vault |
| **Per-Team Permissions** | RSC grants access only to installed teams |
| **No Admin Consent** | Team owners control app installation |
| **Cross-Tenant Ready** | Works in any tenant where the app is installed |

For the full architecture walkthrough — multi-agent orchestration, observability, evaluation, and cross-tenant auth — see [ARTICLE.md](ARTICLE.md).

---

## Quick Start

### Prerequisites

- Azure subscription with permissions to create resources
- Microsoft 365 tenant with Teams
- Python 3.11+
- Azure CLI installed

### 1. Clone and Install

```bash
git clone https://github.com/divssheth/cross-tenant-bot.git
cd cross-tenant-bot
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create Azure Resources

```bash
# Create Resource Group
az group create --name rg-teams-bot --location eastus

# Create User-Assigned Managed Identity
az identity create --name bot-uami --resource-group rg-teams-bot

# Get UAMI details
UAMI_CLIENT_ID=$(az identity show --name bot-uami --resource-group rg-teams-bot --query clientId -o tsv)
UAMI_PRINCIPAL_ID=$(az identity show --name bot-uami --resource-group rg-teams-bot --query principalId -o tsv)

# Create Key Vault
az keyvault create --name bot-keyvault --resource-group rg-teams-bot --location eastus

# Grant UAMI access to Key Vault secrets
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee-object-id $UAMI_PRINCIPAL_ID \
  --scope $(az keyvault show --name bot-keyvault --query id -o tsv)
```

### 3. Create Multi-Tenant App Registration

1. Go to **Azure Portal** → **Microsoft Entra ID** → **App registrations**
2. Click **New registration**
3. Set:
   - Name: `bot-graph-app`
   - Supported account types: **Accounts in any organizational directory** (Multi-tenant)
4. Click **Register**
5. Note the **Application (client) ID** → This is your `GRAPH_APP_ID`
6. Go to **Certificates & secrets** → **New client secret**
7. Copy the secret value

### 4. Store Secret in Key Vault

```bash
az keyvault secret set \
  --vault-name bot-keyvault \
  --name graph-client-secret \
  --value "YOUR_CLIENT_SECRET_VALUE"
```

### 5. Create Azure Bot

1. Go to **Azure Portal** → **Create a resource** → **Azure Bot**
2. Configure:
   - Bot handle: Your bot name
   - Type of App: **User-Assigned Managed Identity**
   - Select your UAMI (`bot-uami`)
3. Set the messaging endpoint after deploying

### 6. Configure Environment

Copy `env.TEMPLATE` to `.env` and fill in:

```bash
# UAMI Configuration
AZURE_CLIENT_ID=<your-uami-client-id>
MICROSOFT_APP_ID=<your-uami-client-id>
AZURE_TENANT_ID=<your-home-tenant-id>
MICROSOFT_APP_TYPE=SingleTenant

# Graph API Configuration
GRAPH_APP_ID=<your-multi-tenant-app-client-id>
KEY_VAULT_NAME=bot-keyvault
GRAPH_CLIENT_SECRET_NAME=graph-client-secret

# Agent Framework
AZURE_AI_ENDPOINT=<your-azure-openai-endpoint>
AZURE_AI_MODEL=gpt-4o
LOCAL_DEBUG=true
LOCAL_TRACING=true
```

### 7. Update Teams Manifest

Ensure your `manifest.json` has:

```json
{
  "webApplicationInfo": {
    "id": "<your-GRAPH_APP_ID>",
    "resource": "https://graph.microsoft.com"
  },
  "authorization": {
    "permissions": {
      "resourceSpecific": [
        { "name": "ChannelMessage.Read.Group", "type": "Application" },
        { "name": "TeamSettings.Read.Group", "type": "Application" },
        { "name": "TeamMember.Read.Group", "type": "Application" },
        { "name": "ChannelSettings.Read.Group", "type": "Application" }
      ]
    }
  }
}
```

**Important:** `webApplicationInfo.id` must match `GRAPH_APP_ID`.

### 8. Run Locally

```bash
cd src
python -m app
```

### 9. Deploy and Install

1. Deploy to Azure Container Apps (or your preferred host)
2. Assign the UAMI to the Container App
3. Package and upload the Teams app to your org's app catalog
4. Install the app in a team

---

## Deployment

The `scripts/deploy-bot.ps1` script automates deployment to Azure Container Apps.

### Configuration

Edit the variables at the top of the script:

```powershell
$script:RESOURCE_GROUP = "your-bot-rg"
$script:LOCATION = "eastus"
$script:ACR_NAME = "yourbotacr"
$script:CONTAINER_ENV_NAME = "your-bot-env"
$script:CONTAINER_APP_NAME = "your-bot-app"
$script:UAMI_NAME = "your-bot-uami"
$script:BOT_APP_ID = "your-graph-app-id"
```

### Commands

```powershell
cd scripts
. .\deploy-bot.ps1

Deploy-BotInfrastructure -ImageTag "v1"  # Full initial deployment
Redeploy-BotCode -ImageTag "v2"          # Code changes only
Update-BotEnvironmentVariables            # Env vars only
Verify-BotDeployment                      # Health check
Get-BotLogs -Tail 100                     # View logs
```

---

## Project Structure

```
├── src/
│   └── app/
│       ├── __main__.py              # Bot entry point and message handlers
│       ├── start_server.py          # aiohttp server startup
│       ├── conversation_state.py    # In-memory conversation tracking + team mapping
│       ├── graph_rsc_client.py      # Graph API client with RSC support
│       ├── log_config.py            # Logging configuration
│       ├── trace_config.py          # Dual-mode telemetry (AI Toolkit / Azure Monitor)
│       ├── agents/
│       │   ├── orchestrator.py      # HandoffBuilder workflow creation
│       │   ├── triage_agent.py      # Router agent (intent classification)
│       │   ├── web_agent.py         # Web search + MCP + acronym tools
│       │   ├── license_agent.py     # Foundry-deployed licensing agent
│       │   ├── foundry_agent_client.py  # Multi-agent orchestration client
│       │   └── _acronyms.py         # Microsoft acronym dictionary
│       └── eval/
│           ├── multi_agent_eval.py  # Multi-agent evaluation runner
│           ├── evaluate_agent.py    # Single-agent evaluation runner
│           └── test_data.json       # Evaluation test cases
├── packages/
│   ├── teams/                       # Teams bot manifest
│   └── copilot/                     # M365 Copilot agent manifest
├── scripts/
│   ├── deploy-bot.ps1               # Deployment automation
│   ├── workbook-template.json       # Azure Monitor Workbook (ARM template)
│   ├── workbook-gallery.json        # Workbook JSON for portal import
│   └── Create-AppPackages.ps1       # Teams & Copilot package builder
├── docs/
│   ├── MULTI_AGENT_ORCHESTRATION.md # Agent architecture deep-dive
│   ├── EVALUATION_GUIDE.md          # Evaluation setup and custom evaluators
│   ├── OBSERVABILITY.md             # Tracing, logging, KQL, dashboards
│   └── KQL_CHEATSHEET.md            # Copy-paste KQL queries for App Insights
├── Dockerfile
├── requirements.txt
├── env.TEMPLATE
├── ARTICLE.md                       # In-depth architecture article
└── README.md
```

---

## Creating App Packages

```powershell
cd scripts

.\Create-AppPackages.ps1              # Create both packages
.\Create-AppPackages.ps1 -TeamsOnly   # Teams Bot only
.\Create-AppPackages.ps1 -CopilotOnly # Copilot Agent only
```

| Package | Location | Description |
|---------|----------|-------------|
| Teams Bot | `packages/teams/CrossTenantBot.zip` | Standard Teams bot for 1:1, group, and channel chats |
| Copilot Agent | `packages/copilot/CrossTenantAgent.zip` | Custom Engine Agent for Microsoft 365 Copilot |

---

## Running Evaluations

The project includes a multi-agent evaluation framework that logs results to Azure AI Foundry.

```bash
cd src

# Run all evaluations and log to Foundry Portal
python -m app.eval.multi_agent_eval --log-to-foundry

# Include agent-specific evaluators (tool usage quality)
python -m app.eval.multi_agent_eval --log-to-foundry --include-agent-evals

# Single-turn only / multi-turn only
python -m app.eval.multi_agent_eval --log-to-foundry --single-turn-only
python -m app.eval.multi_agent_eval --log-to-foundry --multi-turn-only

# Filter by category
python -m app.eval.multi_agent_eval --log-to-foundry --category licensing
```

**Evaluators:** Coherence, Fluency, Relevance, Groundedness, Violence detection, Tool Call Accuracy, Tool Selection, Task Completion, and more.

Results are viewable in **Foundry Portal → Your Project → Evaluations**.

For detailed evaluation setup, see [docs/EVALUATION_GUIDE.md](docs/EVALUATION_GUIDE.md).

---

## Observability

The bot uses [Agent Framework's built-in observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability?pivots=programming-language-python) which auto-instruments agents, chat clients, and tool executions.

| Mode | When | View Results |
|------|------|-------------|
| **AI Toolkit** | `LOCAL_TRACING=true` | VS Code AI Toolkit trace viewer |
| **Azure Monitor** | `APPLICATIONINSIGHTS_CONNECTION_STRING` set | Azure Portal → App Insights |

`LOCAL_TRACING` controls tracing destination; `LOCAL_DEBUG` controls authentication only.

Agent Framework auto-creates `invoke_agent`, `chat`, and `execute_tool` spans plus token usage metrics. Production uses `configure_azure_monitor()` + `enable_instrumentation()` ([Pattern #3](https://learn.microsoft.com/en-us/agent-framework/agents/observability?pivots=programming-language-python#3-third-party-setup)).

For KQL queries, see [docs/KQL_CHEATSHEET.md](docs/KQL_CHEATSHEET.md). For alerts, dashboards, and best practices, see [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md).

---

## Bot Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/info` | Display user and tenant information |
| `/status` | Show bot status and configuration |
| `/context` | Show recent conversation context (uses RSC for channels) |
| `/contextinfo` | Show conversation state details |
| `/rsctest` | Diagnose RSC permissions (use in a channel) |
| `/teamcache` | Show team mapping cache status |

Any other message is routed through the multi-agent workflow.

---

## RSC Troubleshooting

### Verify RSC Permissions

```
GET https://graph.microsoft.com/beta/teams/{team-id}/permissionGrants
```

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `consentedPermissionSet: null` | RSC not consented | Uninstall and reinstall the app |
| 403 with `Group.Selected` | Azure AD permissions conflict | Remove all Graph permissions from Azure AD app |
| External app ID mismatch | Manifest not updated | Republish app with correct `webApplicationInfo.id` |
| Token acquisition fails | Wrong tenant ID | Use the target tenant's ID |
| 403 with "resource not found" | Wrong team_id format | Use M365 Group ID (GUID), not `19:xxx` format |

### Extracting the Correct Team ID

The Graph API requires the **M365 Group ID** (a GUID), not the channel-style `19:xxx@thread.tacv2`:

```python
import re

def extract_team_channel_ids(activity) -> tuple:
    conv_id = activity.conversation.id or ''
    group_match = re.search(r'groupId=([a-f0-9-]+)', conv_id, re.IGNORECASE)
    team_id = group_match.group(1) if group_match else None
    channel_match = re.search(r'(19:[^;]+)', conv_id)
    channel_id = channel_match.group(1) if channel_match else None
    return team_id, channel_id
```

### Azure AD App Permissions

For RSC to work, your Azure AD app should have **minimal or no** API permissions:

✅ **Good:** Empty or just `User.Read` (delegated)  
❌ **Bad:** `Team.ReadBasic.All`, `Group.Read.All`, `ChannelMessage.Read.All`

---

## Environment Variables

### Core Bot Authentication

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_CLIENT_ID` | Yes | UAMI Client ID (also used as Bot App ID) |
| `MICROSOFT_APP_ID` | Yes | Same as AZURE_CLIENT_ID for UAMI bots |
| `AZURE_TENANT_ID` | Yes | Your home tenant ID |
| `MicrosoftAppType` | Yes | Set to `UserAssignedMsi` for UAMI bots |
| `PORT` | No | Server port (default: `3978`) |
| `LOCAL_DEBUG` | No | Set to `true` to skip UAMI auth (agentsplayground/emulator) |
| `LOCAL_TRACING` | No | Set to `true` to send traces to AI Toolkit instead of App Insights |

### Microsoft Graph API (RSC)

| Variable | Required | Description |
|----------|----------|-------------|
| `GRAPH_TENANT_ID` | Yes | Target tenant ID for Graph API calls |
| `GRAPH_APP_ID` | Yes | Multi-tenant app registration Client ID |
| `KEY_VAULT_NAME` | Yes | Azure Key Vault name |
| `GRAPH_CLIENT_SECRET_NAME` | No | Secret name in Key Vault (default: `graph-client-secret`) |
| `ENABLE_RSC` | No | Enable RSC features (default: `false`) |

### Multi-Agent Framework

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_AI_ENDPOINT` | Yes | Azure OpenAI endpoint |
| `AZURE_AI_MODEL` | Yes | Model deployment name (e.g., `gpt-4o`) |
| `AZURE_AI_LICENSE_AGENT_ID` | No | Foundry agent name for license agent (omit to disable) |
| `AZURE_AI_PROJECT_ENDPOINT` | No | Foundry project endpoint for evaluations |
| `AZURE_SEARCH_ENDPOINT` | No | Azure AI Search endpoint for knowledge base |
| `AZURE_SEARCH_INDEX_NAME` | No | Index name in Azure AI Search |

### Telemetry

| Variable | Required | Description |
|----------|----------|-------------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | App Insights connection string for production telemetry |

### Conversation Settings

| Variable | Required | Description |
|----------|----------|-------------|
| `MAX_CONTEXT_MESSAGES` | No | Max messages in conversation state (default: `20`) |
| `MAX_GRAPH_MESSAGES` | No | Max messages from Graph API (default: `50`) |

---

## Security Considerations

1. **No secrets in code or config** — Client secret stored in Key Vault, accessed via UAMI
2. **UAMI for authentication** — No credentials to rotate or leak
3. **Per-team permissions** — RSC scopes access to installed teams only
4. **Minimal Azure AD permissions** — Only what's needed for the app to function
5. **DefaultAzureCredential** — Automatic credential selection for local and production

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARTICLE.md](ARTICLE.md) | In-depth architecture article covering multi-agent orchestration, observability, evaluation, and cross-tenant auth |
| [docs/MULTI_AGENT_ORCHESTRATION.md](docs/MULTI_AGENT_ORCHESTRATION.md) | HandoffBuilder workflow, agent definitions, tool integration |
| [docs/EVALUATION_GUIDE.md](docs/EVALUATION_GUIDE.md) | Evaluation setup, custom evaluators, Foundry SDK integration |
| [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md) | Tracing, logging, KQL queries, alerts, dashboards |
| [src/app/README.md](src/app/README.md) | Module-level architecture and code reference |

---

## License

MIT License

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## Support

- Check the [RSC Troubleshooting](#rsc-troubleshooting) section
- Open a [GitHub issue](https://github.com/divssheth/cross-tenant-bot/issues)
- [Microsoft RSC documentation](https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/rsc/resource-specific-consent)
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
