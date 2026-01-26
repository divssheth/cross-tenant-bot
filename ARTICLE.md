# Building Cross-Tenant Microsoft Teams Bots After the Multi-Tenant Bot Deprecation

## Introduction

On July 31, 2025, Microsoft deprecated the creation of new multi-tenant bots in Azure Bot Service. Existing multi-tenant bots continue to function, but developers building new bots must now choose between single-tenant authentication or user-assigned managed identity (UAMI).

This deprecation creates a practical challenge for enterprise scenarios where bots need to operate across organizational boundaries. Consider a software vendor providing a Teams bot to customers, or a corporate platform team deploying automation bots across subsidiary tenants. The multi-tenant bot pattern elegantly handled these scenarios. What replaces it?

This article explains how to build a cross-tenant capable Teams bot using UAMI for authentication while leveraging Resource-Specific Consent (RSC) for Graph API access across tenants.

## Understanding the Deprecation

Microsoft's official documentation now states:

> Multi-tenant bot creation will be deprecated after July 31, 2025. Existing multi-tenant bots will continue to function, but new multi-tenant bot creation will no longer be supported after that date. To ensure continued support, use single-tenant or user-assigned managed identity going forward.

The deprecation applies specifically to the Azure Bot resource's authentication type. When creating an Azure Bot, you previously had three options:

1. **Multi-tenant** - Bot works in any Azure AD tenant (deprecated for new bots)
2. **Single-tenant** - Bot works only in one Azure AD tenant
3. **User-Assigned Managed Identity** - Bot authenticates using an Azure managed identity

With multi-tenant no longer available for new bots, UAMI becomes the recommended approach for new development.

## The Cross-Tenant Challenge

At first glance, UAMI appears to limit bots to single-tenant scenarios. A managed identity belongs to one Azure subscription in one tenant. How can this identity enable cross-tenant communication?

The answer lies in understanding what UAMI actually authenticates: the bot's communication with Azure Bot Framework, not the end-user interactions.

When a user in Tenant B sends a message to your bot hosted in Tenant A:

1. The message travels through Microsoft's Bot Framework Service
2. Bot Framework routes it to your bot's messaging endpoint
3. Your bot processes the message and sends a response
4. Bot Framework routes the response back to the user in Tenant B

The Bot Framework handles the cross-tenant routing transparently. Your bot's UAMI authentication proves your bot's identity to Bot Framework. It does not restrict which tenants can communicate with your bot.

However, if your bot needs to call Microsoft Graph API to access resources in Tenant B (such as reading channel messages), you need a separate authentication mechanism. This is where Resource-Specific Consent enters the picture.

## The Architecture

The solution uses two distinct identities:

### Identity 1: User-Assigned Managed Identity (UAMI)

Purpose:
- Authenticate to Azure Bot Framework for sending/receiving messages
- Authenticate to Azure Key Vault for retrieving secrets
- No secrets stored in code or configuration

The UAMI is created in your home tenant (Tenant A) and assigned to your bot's compute resource (Azure Container Apps, App Service, etc.).

### Identity 2: Multi-Tenant App Registration

Purpose:
- Authenticate to Microsoft Graph API in any tenant where the app is installed
- Uses client credentials flow with a client secret
- The secret is stored in Key Vault and accessed via UAMI

This is not a multi-tenant *bot*—it is a multi-tenant *app registration* used solely for Graph API access. The distinction matters: Microsoft deprecated multi-tenant bot authentication, not multi-tenant app registrations.

### Resource-Specific Consent (RSC)

RSC is a Teams-specific authorization model that allows apps to request permissions scoped to individual teams or chats rather than requiring tenant-wide admin consent.

When a team owner installs your Teams app, they consent to the RSC permissions declared in your app manifest. These permissions apply only to that specific team. No global admin involvement is required.

RSC permissions include:

- `ChannelMessage.Read.Group` - Read messages in a team's channels
- `TeamSettings.Read.Group` - Read team settings
- `TeamMember.Read.Group` - Read team membership
- `ChannelSettings.Read.Group` - Read channel settings

This model aligns well with cross-tenant scenarios. Each tenant's team owners control which teams grant access to your bot.

### When Is Graph API Access Actually Needed?

Not all bot scenarios require Graph API access. The need depends on the conversation type and your storage strategy:

**1:1 and Group Chat Conversations**

For personal (1:1) and group chat conversations, your bot receives all messages directly through Bot Framework. The conversation history is delivered to your bot in real-time as users interact. You can store these messages in your own database. Graph API access is typically unnecessary for these scenarios.

**Channel Conversations**

Channel conversations are different. Your bot only receives messages where it is explicitly mentioned or that match configured keywords. To access the full channel message history—including messages your bot was not mentioned in—you need Graph API with RSC permissions.

However, even for channels, Graph API access is optional:

- **If you store channel messages**: When your bot is mentioned, you can save the conversation context to your own storage. Future requests can reference your stored data without calling Graph API.

- **If you don't store messages**: You need Graph API to retrieve channel history on demand. This is where RSC permissions become essential.

**Design Decision**

The choice between storing messages locally versus retrieving them via Graph API depends on your requirements:

**Store locally:**
- Pros: No Graph API needed, faster retrieval, works offline
- Cons: Storage costs, data sync complexity, stale data risk

**Retrieve via Graph API:**
- Pros: Always current data, no storage management
- Cons: Requires RSC permissions, API rate limits, beta endpoint dependency

This reference implementation demonstrates Graph API access with RSC because it addresses the more complex scenario. For simpler bots that only need real-time conversation context, you may not need Graph API access at all.

## Authentication Flow

Here is how authentication works end-to-end:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Your Tenant (Tenant A)                          │
│                                                                      │
│  ┌──────────────┐     ┌──────────────┐     ┌───────────────────┐    │
│  │     UAMI     │────▶│  Key Vault   │     │ Multi-Tenant App  │    │
│  │  (Bot Auth)  │     │  (Secrets)   │     │  (Graph API)      │    │
│  └──────┬───────┘     └──────┬───────┘     └─────────┬─────────┘    │
│         │                    │                       │               │
│         │                    └───────────────────────┤               │
│         ▼                                            ▼               │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Your Bot Container                        │    │
│  │  1. Uses UAMI for Bot Framework authentication               │    │
│  │  2. Uses UAMI to retrieve client secret from Key Vault       │    │
│  │  3. Uses client secret to get Graph API token for Tenant B   │    │
│  │     via client credentials flow                              │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
                              │
                              │ Bot Framework handles cross-tenant routing
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   External Tenant (Tenant B)                         │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Team with your app installed                                │    │
│  │  - RSC permissions granted by team owner at install          │    │
│  │  - Bot reads channel messages via Graph API                  │    │
│  │  - Token acquired using Tenant B's ID                        │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

When a user in Tenant B messages your bot:

1. Your bot receives the message via Bot Framework (authenticated by UAMI in Tenant A)
2. The message contains the user's tenant ID (Tenant B) in the activity metadata
3. If your bot needs to call Graph API for Tenant B:
   - UAMI retrieves the client secret from Key Vault in Tenant A
   - Bot requests a token from Tenant B using client credentials flow
   - Bot calls Graph API with the token
   - RSC permissions (granted when the app was installed in Tenant B) authorize the request

## Implementation Details

### Teams App Manifest

The manifest must declare RSC permissions and link to your multi-tenant app registration:

```json
{
  "webApplicationInfo": {
    "id": "YOUR-MULTI-TENANT-APP-ID",
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

The `webApplicationInfo.id` must match the multi-tenant app registration used for Graph API calls. This is how Teams knows which app receives the RSC permissions.

### Azure AD App Configuration

The multi-tenant app registration requires minimal configuration:

- **Supported account types**: Accounts in any organizational directory (Multi-tenant)
- **API Permissions**: None required in Azure AD portal—RSC permissions are granted through Teams
- **Client Secret**: Generated and stored in Key Vault

A critical point: Do not add Graph API permissions (like `ChannelMessage.Read.All`) to this app registration. Adding Azure AD permissions causes Graph API to use those instead of RSC permissions, breaking the per-team scoping model.

### Acquiring Tokens for External Tenants

When calling Graph API for a resource in Tenant B, request the token from that tenant's token endpoint:

```python
async def get_app_token(tenant_id: str) -> str:
    """Get Graph API token for the specified tenant."""
    
    # Retrieve client secret from Key Vault via UAMI
    client_secret = await get_secret_from_keyvault("graph-client-secret")
    
    # Request token from the TARGET tenant (Tenant B)
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    
    async with aiohttp.ClientSession() as session:
        data = {
            "grant_type": "client_credentials",
            "client_id": GRAPH_APP_ID,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default"
        }
        
        async with session.post(token_url, data=data) as response:
            result = await response.json()
            return result["access_token"]
```

The tenant ID comes from the incoming Teams activity:

```python
def extract_tenant_id(activity) -> str:
    """Extract tenant ID from Teams activity."""
    channel_data = activity.channel_data or {}
    tenant = channel_data.get("tenant", {})
    return tenant.get("id")
```

### Reading Channel Messages with RSC

With RSC permissions, you can read channel messages without user authentication:

```python
async def get_channel_messages(team_id: str, channel_id: str, tenant_id: str):
    """Read channel messages using RSC permissions."""
    
    token = await get_app_token(tenant_id)
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Beta endpoint required for RSC channel message access
    url = f"https://graph.microsoft.com/beta/teams/{team_id}/channels/{channel_id}/messages"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            return data.get("value", [])
```

Note the use of the beta endpoint. As of this writing, RSC-based channel message access requires the beta API.

### Fetching Message Replies

The Graph API returns only top-level messages from the messages endpoint. Replies require a separate call:

```python
async def get_message_replies(team_id: str, channel_id: str, message_id: str, tenant_id: str):
    """Fetch replies to a specific message."""
    
    token = await get_app_token(tenant_id)
    
    url = f"https://graph.microsoft.com/beta/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"
    
    # ... make request and return replies
```

## Common Pitfalls

### RSC Permissions Not Being Granted

Symptoms: Graph API returns 403 Forbidden with permission errors.

Causes and solutions:

1. **App ID mismatch**: The `webApplicationInfo.id` in your manifest must match the app ID your bot uses for Graph API calls.

2. **Azure AD permissions conflict**: If your app registration has any Graph API permissions configured in Azure AD (like `Team.ReadBasic.All`), Graph uses those instead of RSC. Remove all Graph permissions from the Azure AD app.

3. **Manifest not updated**: After changing `webApplicationInfo.id`, you must republish the Teams app and reinstall it in each team.

4. **Tenant RSC policy**: The target tenant may have RSC disabled. Check Teams Admin Center settings.

### Verifying RSC Permissions

Use Graph Explorer to check if RSC permissions are granted for a team:

```
GET https://graph.microsoft.com/beta/teams/{team-id}/permissionGrants
```

The response should list each RSC permission granted to your app.

### Token Acquisition Failing for External Tenants

Ensure your multi-tenant app registration is configured for "Accounts in any organizational directory." Single-tenant app registrations cannot acquire tokens for other tenants.

### Beta Endpoint Required for RSC

RSC-based channel message access currently requires the Graph API beta endpoint (`graph.microsoft.com/beta`). The v1.0 endpoint does not support RSC for channel messages. If you're getting permission errors with v1.0, switch to the beta endpoint.

## Security Considerations

This architecture provides several security benefits:

1. **No secrets in code**: The client secret lives only in Key Vault in Tenant A. UAMI accesses Key Vault without credentials.

2. **Per-team scoping**: RSC permissions apply only to teams where the app is installed. Unlike tenant-wide permissions, a compromised token cannot access other teams in Tenant B.

3. **Team owner control**: Team owners in Tenant B decide whether to install your app. Global admins are not required for RSC consent.

4. **Credential rotation**: Rotating the client secret requires only updating Key Vault in Tenant A. No application redeployment needed.

## Conclusion

Microsoft's deprecation of multi-tenant bot creation does not prevent building bots that work across organizational boundaries. By combining UAMI for bot authentication with a separate multi-tenant app registration for Graph API access, you can build cross-tenant capable bots that follow Microsoft's current guidance.

The key architectural insights are:

- UAMI authenticates your bot to Bot Framework in Tenant A; it does not restrict which tenants can message your bot
- A separate multi-tenant app registration handles Graph API authentication across tenants (Tenant A, B, C, etc.)
- RSC permissions enable per-team authorization without tenant-wide admin consent
- Azure Key Vault in Tenant A secures the client secret, accessed via UAMI

I have published a complete reference implementation including deployment automation and detailed documentation:

**Repository**: https://github.com/divssheth/cross-tenant-bot

**Microsoft Documentation**: https://learn.microsoft.com/en-us/azure/bot-service/bot-service-quickstart-registration?view=azure-bot-service-4.0&tabs=userassigned

---

*Divyesh Sheth is a software engineer focused on Microsoft 365 platform development.*
