# Cross-Tenant Teams Bot with UAMI and RSC

A Microsoft Teams bot that uses **User-Assigned Managed Identity (UAMI)** for secure authentication and **Resource-Specific Consent (RSC)** for reading channel messages—without requiring user sign-in or tenant-wide admin consent.

## Why This Architecture?

### The Problem with Traditional Multi-Tenant Bots

Traditional multi-tenant bots use a **multi-tenant app registration with a client secret** for Bot Framework authentication. This creates several challenges:

| Challenge | Description |
|-----------|-------------|
| **Secret Management** | Client secrets must be stored, rotated, and secured |
| **Tenant-Wide Consent** | Graph API permissions require admin consent in every tenant |
| **Security Risk** | Leaked secrets can compromise all tenant installations |
| **Operational Overhead** | Secret rotation requires coordinated deployments |

### The UAMI + RSC Solution

This architecture separates concerns and eliminates secrets:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Your Tenant (Home)                            │
│                                                                      │
│  ┌──────────────┐     ┌──────────────┐     ┌───────────────────┐    │
│  │     UAMI     │────►│  Key Vault   │     │ Multi-Tenant App  │    │
│  │  (Bot Auth)  │     │  (Secrets)   │     │  (Graph API/RSC)  │    │
│  └──────┬───────┘     └──────┬───────┘     └─────────┬─────────┘    │
│         │                    │                       │               │
│         │                    └───────────────────────┤               │
│         ▼                                            ▼               │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Your Bot (Container)                      │    │
│  │  • Uses UAMI for Bot Framework (no secrets in code)          │    │
│  │  • Retrieves Graph secret from Key Vault via UAMI            │    │
│  │  • Calls Graph API with tenant-specific tokens               │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              │ Bot Framework (handles cross-tenant routing)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      External Tenant (Customer)                      │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Team with App Installed                                     │    │
│  │  ├─ RSC permissions granted at install (no admin consent)   │    │
│  │  ├─ Bot reads channel messages via Graph API                 │    │
│  │  └─ Per-team scoping (not tenant-wide access)               │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### Key Benefits

| Benefit | Description |
|---------|-------------|
| **No Secrets in Code** | UAMI authenticates to Bot Framework and Key Vault without credentials |
| **Per-Team Permissions** | RSC grants access only to teams where the app is installed |
| **No Admin Consent** | Team owners can install the app and grant RSC permissions |
| **Secure Secret Storage** | Graph API secret stored in Key Vault, accessed via UAMI |
| **Cross-Tenant Ready** | Works in any tenant where the Teams app is installed |

---

## Architecture Components

### 1. User-Assigned Managed Identity (UAMI)
- Authenticates the bot to Azure Bot Framework
- Accesses Key Vault to retrieve the Graph API client secret
- No secrets stored in environment variables or code

### 2. Multi-Tenant App Registration
- Used for Microsoft Graph API authentication
- Configured with RSC permissions in the Teams manifest
- Client secret stored in Key Vault (not in the app)

### 3. Azure Key Vault
- Securely stores the Graph API client secret
- UAMI has "Key Vault Secrets User" role
- Secret retrieved at runtime, never stored locally

### 4. Resource-Specific Consent (RSC)
- Permissions declared in the Teams app manifest
- Granted when a team owner installs the app
- Scoped to the specific team (not tenant-wide)

---

## Quick Start

### Prerequisites

- Azure subscription with permissions to create resources
- Microsoft 365 tenant with Teams
- Python 3.10+
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

### 8. Deploy and Install

1. Deploy to Azure Container Apps (or your preferred host)
2. Assign the UAMI to the Container App
3. Package and upload the Teams app to your org's app catalog
4. Install the app in a team

---

## Deployment Script

The `scripts/deploy-bot.ps1` script automates deployment to Azure Container Apps.

### Prerequisites

- Azure CLI installed and logged in (`az login`)
- PowerShell 5.1+ or PowerShell Core
- Existing UAMI and Azure Bot resource (see Quick Start steps 1-5)

### Configuration

Before running, edit the configuration variables at the top of the script:

```powershell
$script:RESOURCE_GROUP = "your-bot-rg"           # Your Azure resource group
$script:LOCATION = "eastus"                       # Azure region
$script:ACR_NAME = "yourbotacr"                  # Container registry name (globally unique)
$script:CONTAINER_ENV_NAME = "your-bot-env"      # Container Apps environment name
$script:CONTAINER_APP_NAME = "your-bot-app"      # Container App name
$script:UAMI_NAME = "your-bot-uami"              # Your UAMI name
$script:BOT_APP_ID = "your-graph-app-id"         # Multi-tenant app ID (GRAPH_APP_ID)
```

### Usage

```powershell
# Load the script
cd scripts
. .\deploy-bot.ps1

# Show available commands
Show-Help
```

### Available Commands

| Command | Description |
|---------|-------------|
| `Deploy-BotInfrastructure` | Full deployment: creates ACR, Container Apps Environment, and Container App |
| `Redeploy-BotCode` | Rebuilds image and updates Container App (use for code changes) |
| `Update-BotEnvironmentVariables` | Updates env vars without rebuilding |
| `Verify-BotDeployment` | Checks all configurations and displays details |
| `Get-BotEndpoint` | Gets the bot's messaging endpoint URL |
| `Get-BotLogs` | Views Container App logs |

### Common Workflows

#### Initial Deployment

```powershell
. .\deploy-bot.ps1
Deploy-BotInfrastructure -ImageTag "v1"
```

This will:
1. Create Azure Container Registry
2. Build and push the Docker image
3. Create Container Apps Environment
4. Assign AcrPull role to UAMI
5. Create Container App with UAMI and environment variables

#### Deploying Code Changes

```powershell
. .\deploy-bot.ps1
Redeploy-BotCode -ImageTag "v2"

# Or use auto-generated timestamp tag
Redeploy-BotCode
```

#### Updating Environment Variables

```powershell
. .\deploy-bot.ps1
Update-BotEnvironmentVariables -EnvFile ".env.prod"
```

#### Troubleshooting

```powershell
# Verify all configurations
Verify-BotDeployment

# View logs
Get-BotLogs -Tail 100

# Stream logs in real-time
Get-BotLogs -Follow

# Get endpoint URL (copies to clipboard)
Get-BotEndpoint
```

---

## Project Structure

```
├── src/
│   └── app/
│       ├── __init__.py
│       ├── __main__.py           # Bot entry point and message handlers
│       ├── agents/               # AI agent clients
│       │   └── foundry_agent_client.py
│       ├── eval/                 # Agent evaluation framework
│       │   ├── evaluate_agent.py
│       │   └── test_data.json
│       ├── conversation_state.py  # In-memory conversation tracking + team mapping cache
│       ├── graph_rsc_client.py    # Graph API client with RSC support
│       ├── log_config.py          # Logging configuration
│       ├── start_server.py        # aiohttp server startup
│       └── trace_config.py        # Telemetry configuration
├── packages/
│   ├── teams/                     # Teams bot manifest
│   │   ├── manifest.json
│   │   ├── color.png
│   │   └── outline.png
│   └── copilot/                   # M365 Copilot agent manifest
│       ├── manifest.template.json
│       ├── color.png
│       └── outline.png
├── scripts/
│   ├── deploy-bot.ps1             # Deployment automation script
│   └── Create-AppPackages.ps1     # Creates Teams & Copilot app packages
├── docs/                          # Documentation
├── tests/                         # Unit tests (future)
├── Dockerfile                     # Container image definition
├── requirements.txt               # Python dependencies
├── env.TEMPLATE                   # Environment variable template
└── README.md                      # This file
```

---

## Creating App Packages

### Using the Script

The `scripts/Create-AppPackages.ps1` script creates both Teams Bot and Copilot Agent packages:

```powershell
cd scripts

# Create both packages
.\Create-AppPackages.ps1

# Create Teams Bot package only
.\Create-AppPackages.ps1 -TeamsOnly

# Create Copilot Agent package only
.\Create-AppPackages.ps1 -CopilotOnly
```

### Output Files

| Package | Location | Description |
|---------|----------|-------------|
| Teams Bot | `packages/teams/CrossTenantBot.zip` | Standard Teams bot for 1:1, group, and channel chats |
| Copilot Agent | `packages/copilot/CrossTenantAgent.zip` | Custom Engine Agent for Microsoft 365 Copilot |

### Teams Bot vs Copilot Agent

| Feature | Teams Bot | Copilot Agent |
|---------|-----------|---------------|
| Manifest Version | 1.16 | 1.22 |
| Scopes | personal, team, groupChat | personal, team, groupChat, **copilot** |
| Works in | Teams chats and channels | Microsoft 365 Copilot |
| Authentication | Bot Service routing | Requires app consent |
| Multi-tenant | Works via Bot Service | **Requires multi-tenant app registration** |
| RSC Support | Yes | No (RSC removed for Copilot compatibility) |

### Copilot Agent Requirements

⚠️ **Important:** To use the Copilot Agent in external tenants:

1. **Make your app registration multi-tenant:**
   - Azure Portal → App Registration → Authentication
   - Change to: "Accounts in any organizational directory (Any Microsoft Entra ID tenant)"
   - Save

2. **Users need Microsoft 365 Copilot license**

3. **App must be approved/installed in their tenant**

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
| `/teamcache` | Show team mapping cache status (aadGroupId lookup) |

---

## RSC Troubleshooting

### Verify RSC Permissions are Granted

Use Graph Explorer to check:

```
GET https://graph.microsoft.com/beta/teams/{team-id}/permissionGrants
```

Expected response includes entries with your app's `clientAppId`.

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `consentedPermissionSet: null` | RSC not consented | Uninstall and reinstall the app |
| 403 with `Group.Selected` | Azure AD permissions conflict | Remove all Graph permissions from Azure AD app |
| External app ID mismatch | Manifest not updated | Republish app with correct `webApplicationInfo.id` |
| Token acquisition fails | Wrong tenant ID | Ensure you're using the target tenant's ID |
| 403 with "resource not found" | Wrong team_id format | Use M365 Group ID (GUID), not the channel-style `19:xxx` format |

### Extracting the Correct Team ID for Graph API

The Graph API requires the **M365 Group ID** (a GUID) as the `team_id` parameter, not the channel-style `19:xxx@thread.tacv2` format.

The `conversation.id` in channel activities contains the Group ID in this format:
```
19:abc123@thread.tacv2;groupId=12345678-1234-1234-1234-123456789abc;tenantId=...
```

Extract the `groupId` value using regex:
```python
import re

def extract_team_channel_ids(activity) -> tuple:
    conv_id = activity.conversation.id or ''
    
    # Extract M365 Group ID (required for Graph API)
    group_match = re.search(r'groupId=([a-f0-9-]+)', conv_id, re.IGNORECASE)
    team_id = group_match.group(1) if group_match else None
    
    # Extract channel ID (the 19:xxx part)
    channel_match = re.search(r'(19:[^;]+)', conv_id)
    channel_id = channel_match.group(1) if channel_match else None
    
    return team_id, channel_id
```

**Note:** The `channel_data.team.id` field may return the channel-style ID (`19:xxx`), which will cause 403 errors when used with Graph API. Always extract `groupId` from `conversation.id` for reliable results.

### Azure AD App Permissions

For RSC to work, your Azure AD app should have **minimal or no** API permissions:

✅ **Good:** Empty or just `User.Read` (delegated)  
❌ **Bad:** `Team.ReadBasic.All`, `Group.Read.All`, `ChannelMessage.Read.All`

RSC permissions are declared in the Teams manifest and granted at app install time—not in Azure AD.

---

## Environment Variables Reference

### Core Bot Authentication

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_CLIENT_ID` | Yes | UAMI Client ID (also used as Bot App ID) |
| `MICROSOFT_APP_ID` | Yes | Same as AZURE_CLIENT_ID for UAMI bots |
| `AZURE_TENANT_ID` | Yes | Your home tenant ID |
| `MicrosoftAppType` | Yes | Set to `UserAssignedMsi` for UAMI bots |
| `PORT` | No | Server port (default: `3978`) |
| `LOCAL_DEBUG` | No | Set to `true` for local development with AzureCliCredential |

### Microsoft Graph API (RSC)

| Variable | Required | Description |
|----------|----------|-------------|
| `GRAPH_TENANT_ID` | Yes | Target tenant ID for Graph API calls |
| `GRAPH_APP_ID` | Yes | Multi-tenant app registration Client ID |
| `KEY_VAULT_NAME` | Yes | Azure Key Vault name |
| `GRAPH_CLIENT_SECRET_NAME` | No | Secret name in Key Vault (default: `graph-client-secret`) |
| `ENABLE_RSC` | No | Enable RSC features (default: `false`) |

### Azure AI Foundry (Agent Framework)

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_AI_ENDPOINT` | Yes | Azure OpenAI endpoint (e.g., `https://your-resource.openai.azure.com/`) |
| `AZURE_AI_MODEL` | Yes | Model deployment name (e.g., `gpt-4o`) |
| `AZURE_AI_AGENT_NAME` | No | Agent name (default: `teams-bot-agent`) |
| `AZURE_AI_MAX_TOKENS` | No | Max tokens for responses (default: `1000`) |
| `AZURE_AI_PROJECT_ENDPOINT` | No | Foundry project endpoint for evaluations (format: `https://<account>.services.ai.azure.com/api/projects/<project>`) |

### Azure AI Search (Knowledge Base)

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_SEARCH_ENDPOINT` | No | Azure AI Search endpoint for knowledge base |
| `AZURE_SEARCH_INDEX_NAME` | No | Index name in Azure AI Search |

### Telemetry (Application Insights)

| Variable | Required | Description |
|----------|----------|-------------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | Connection string from Application Insights for telemetry |

### Conversation Settings

| Variable | Required | Description |
|----------|----------|-------------|
| `MAX_CONTEXT_MESSAGES` | No | Max messages in conversation state (default: `20`) |
| `MAX_GRAPH_MESSAGES` | No | Max messages from Graph API (default: `50`) |

---

## Azure AI Foundry Agent Integration

This bot uses **Microsoft Agent Framework** to connect to Azure AI Foundry, providing:

- **Persistent agent registration** in Foundry
- **Foundry-native observability** with automatic tracing
- **Web search tool** for real-time information (Bing grounding)
- **Knowledge base integration** via Azure AI Search

### Agent Configuration

The agent is configured in [src/app/agents/foundry_agent_client.py](src/app/agents/foundry_agent_client.py):

```python
from agent_framework import ChatAgent, HostedWebSearchTool, HostedMCPTool
from agent_framework.azure import AzureOpenAIResponsesClient

# Agent is configured via environment variables
# AZURE_AI_ENDPOINT, AZURE_AI_MODEL, AZURE_AI_AGENT_NAME
```

### Local Development

For local development, set `LOCAL_DEBUG=true` to use your Azure CLI credentials:

```bash
# Login to Azure CLI (use the correct tenant)
az login --tenant YOUR_TENANT_ID

# Set local debug mode
echo "LOCAL_DEBUG=true" >> .env
```

---

## Running Agent Evaluations

The project includes a comprehensive evaluation framework in [src/app/eval/](src/app/eval/):

### Quick Start

```bash
cd src/app/eval

# Run all evaluations locally
python evaluate_agent.py

# Run evaluations and log to Foundry Portal
python evaluate_agent.py --log-to-foundry

# Include agent-specific evaluators
python evaluate_agent.py --log-to-foundry --include-agent-evals
```

### Evaluation Types

| Type | Description |
|------|-------------|
| Single-turn | Individual question/answer pairs |
| Multi-turn | Conversational sequences |

### Built-in Evaluators

**Quality Evaluators:**
- Coherence, Fluency, Relevance, Groundedness

**Safety Evaluators:**
- Violence detection

**Agent Evaluators** (with `--include-agent-evals`):
- Tool Call Accuracy, Tool Call Success, Tool Input Accuracy
- Tool Output Utilization, Tool Selection, Task Completion

### CLI Options

```bash
python evaluate_agent.py --help

Options:
  --log-to-foundry       Log results to Foundry Portal
  --include-agent-evals  Include agent-specific evaluators
  --single-turn-only     Run only single-turn evaluations
  --multi-turn-only      Run only multi-turn evaluations
  --category CATEGORY    Filter by test category
  --evaluation-name NAME Custom evaluation name
```

See [test_data.json](src/app/eval/test_data.json) for evaluation test cases.

---

## Telemetry & Observability

The bot includes comprehensive observability with Azure Monitor and Application Insights.

### Configuration

Telemetry is automatically enabled when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set:

```python
# src/app/trace_config.py
from azure.monitor.opentelemetry import configure_azure_monitor

configure_azure_monitor(
    connection_string=os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"),
    enable_live_metrics=True,
)
```

### Features

- **Distributed tracing** - Track requests across bot and agent
- **Structured logging** - Contextual logs with conversation IDs
- **Custom metrics** - Track agent response times, tool usage
- **Live metrics** - Real-time performance monitoring

### Documentation

For detailed guidance, see:
- [Observability Best Practices](docs/OBSERVABILITY_BEST_PRACTICES.md) - Comprehensive guide
- [Observability Cheatsheet](docs/OBSERVABILITY_CHEATSHEET.md) - Quick reference

---

## Security Considerations

1. **No secrets in code or config files** - All secrets in Key Vault
2. **UAMI for authentication** - No credentials to rotate or leak
3. **Per-team permissions** - RSC scopes access to installed teams only
4. **Minimal Azure AD permissions** - Only what's needed for the app to function

---

## License

MIT License - See LICENSE file for details.

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## Support

For issues and questions:
- Check the [Troubleshooting](#rsc-troubleshooting) section
- Open a GitHub issue
- Review Microsoft's [RSC documentation](https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/rsc/resource-specific-consent)
