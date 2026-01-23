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
git clone <your-repo>
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

The `devTools/deploy-bot.ps1` script automates deployment to Azure Container Apps.

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
cd devTools
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
├── app/
│   ├── __init__.py
│   ├── __main__.py           # Bot entry point and message handlers
│   ├── conversation_state.py  # In-memory conversation tracking
│   ├── graph_rsc_client.py    # Graph API client with RSC support
│   ├── log_config.py          # Logging configuration
│   ├── start_server.py        # aiohttp server startup
│   └── trace_config.py        # Telemetry configuration
├── devTools/
│   └── deploy-bot.ps1         # Deployment automation script
├── TeamsAppPackage/
│   ├── manifest.json          # Teams app manifest with RSC
│   ├── color.png
│   └── outline.png
├── Dockerfile                 # Container image definition
├── requirements.txt           # Python dependencies
├── env.TEMPLATE              # Environment variable template
└── README.md                 # This file
```

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

### Azure AD App Permissions

For RSC to work, your Azure AD app should have **minimal or no** API permissions:

✅ **Good:** Empty or just `User.Read` (delegated)  
❌ **Bad:** `Team.ReadBasic.All`, `Group.Read.All`, `ChannelMessage.Read.All`

RSC permissions are declared in the Teams manifest and granted at app install time—not in Azure AD.

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_CLIENT_ID` | Yes | UAMI Client ID (also used as Bot App ID) |
| `MICROSOFT_APP_ID` | Yes | Same as AZURE_CLIENT_ID for UAMI bots |
| `AZURE_TENANT_ID` | Yes | Your home tenant ID |
| `MICROSOFT_APP_TYPE` | Yes | Always `SingleTenant` for UAMI bots |
| `GRAPH_APP_ID` | Yes | Multi-tenant app registration Client ID |
| `KEY_VAULT_NAME` | Yes | Azure Key Vault name |
| `GRAPH_CLIENT_SECRET_NAME` | No | Secret name in Key Vault (default: `graph-client-secret`) |
| `PORT` | No | Server port (default: `3978`) |

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
