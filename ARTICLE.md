# Building a Production Multi-Agent Teams Bot with Microsoft Agent Framework

## Introduction

Building an AI assistant that genuinely helps users requires more than a single prompt and a model. Users ask about different domains, need current information from the web, and expect answers grounded in organizational knowledge. A single monolithic agent quickly buckles under these demands — bloated system prompts, conflicting tool sets, and no way to evaluate or improve specific capabilities.

Microsoft Agent Framework solves this by enabling **multi-agent orchestration**: a triage agent classifies user intent and hands off to specialist agents, each with focused instructions, appropriate tools, and independently evaluable behavior. Combined with M365 Bot Service for Teams integration, you get a production-grade AI assistant that routes questions intelligently, traces every decision, and can be evaluated before each deployment.

This article walks through the complete lifecycle of building such a system:

1. **Architecture** — How the pieces fit together: Teams, Bot Framework, Agent Framework, and specialist agents
2. **Multi-agent orchestration** — HandoffBuilder workflows, agent definitions, MCP tools, and Foundry-deployed agents
3. **Enterprise observability** — Dual-mode tracing (local AI Toolkit + Azure Monitor), auto-instrumented spans, custom span enrichment, structured logging
4. **Agent evaluation** — Quality, safety, and agent-specific evaluators; custom evaluators; single-turn and multi-turn testing
5. **Monitoring dashboards** — Pre-built Azure Workbook with seven operational tabs
6. **Development workflow** — Inner loop / outer loop separation, evaluation as a quality gate
7. **Cross-tenant authentication** — How to extend the bot to serve users across organizational boundaries using UAMI and RSC

The reference implementation is a Microsoft Teams bot with three agents: a triage agent for intent classification, a web agent with Bing search, Microsoft Learn MCP integration, and acronym decoding, and a license agent backed by a Foundry-deployed knowledge base.

## Architecture Overview

The system spans four layers: the Teams user interface, Microsoft's Bot Framework for message routing, Agent Framework for multi-agent orchestration, and Azure services for observability and evaluation.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Microsoft Teams                                    │
│  Users send messages in channels or 1:1 chats                                │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      M365 Bot Service (Bot Framework)                        │
│  Routes messages to bot endpoint, handles auth, supports cross-tenant        │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Bot Application (Azure Container Apps)                    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │              Microsoft Agent Framework (HandoffBuilder)               │    │
│  │                                                                      │    │
│  │  Triage Agent ──┬──▶ Web Agent                                       │    │
│  │  (intent         │    ├── Bing Web Search                            │    │
│  │   classification)│    ├── Microsoft Learn MCP Server                 │    │
│  │                  │    └── Acronym Decoder (@ai_function)             │    │
│  │                  │                                                   │    │
│  │                  └──▶ License Agent                                  │    │
│  │                       └── Azure AI Foundry Agent (knowledge base)    │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────┐  ┌──────────────────────┐                         │
│  │  Telemetry            │  │  Auth                 │                         │
│  │  ├── AI Toolkit (dev) │  │  ├── UAMI (Bot Auth)  │                         │
│  │  └── Azure Monitor    │  │  └── DefaultAzure-    │                         │
│  │      (production)     │  │      Credential (AI)  │                         │
│  └──────────────────────┘  └──────────────────────┘                         │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                          ┌─────────┼─────────┐
                          ▼                   ▼
┌───────────────────────────────┐  ┌─────────────────────────────────────────┐
│  Azure Monitor / App Insights  │  │  Azure AI Foundry                        │
│  ├── Traces & Spans            │  │  ├── Agent Deployment                    │
│  ├── Metrics (tokens, latency) │  │  ├── Evaluation Portal                  │
│  ├── Logs (customDimensions)   │  │  └── Azure AI Search (knowledge base)   │
│  └── Workbook Dashboard        │  │                                          │
└───────────────────────────────┘  └─────────────────────────────────────────┘
```

**Authentication** uses User-Assigned Managed Identity (UAMI) for Bot Framework communication and `DefaultAzureCredential` for Azure OpenAI and Foundry access. No secrets in code — UAMI in production, `az login` locally. For cross-tenant scenarios (serving users in other organizations), a separate multi-tenant app registration with RSC permissions handles Graph API access; this is covered in the [Cross-Tenant Authentication](#cross-tenant-authentication) section.

**Orchestration** uses Agent Framework's `HandoffBuilder` to compose agents into a workflow with controlled routing and termination conditions.

**Observability** is dual-mode: the same instrumentation code sends spans to VS Code AI Toolkit during development and to Azure Monitor in production.

**Evaluation** runs locally or in CI/CD, combining custom evaluators with Azure AI Foundry's built-in quality, safety, and agent evaluators.

## Multi-Agent Orchestration

### Why Multiple Agents?

A single agent handling all user questions quickly runs into limitations: bloated system prompts, conflicting tool sets, and difficulty evaluating specific capabilities. By decomposing into specialist agents, each agent has focused instructions, appropriate tools, and can be evaluated independently.

### Architecture: HandoffBuilder Workflow

The bot uses Agent Framework's `HandoffBuilder` to create a workflow where a triage agent routes questions to specialists:

```
User Message → Triage Agent → [routing decision]
                                  │
                   ┌──────────────┼──────────────┐
                   ▼              ▼               ▼
              Web Agent    License Agent    Direct Response
              (search,     (Foundry         (greetings,
               MCP,         deployed,        non-Microsoft)
               acronyms)    knowledge
                            base)
```

The triage agent analyzes user intent and calls a handoff function (`handoff_to_web_agent` or `handoff_to_license_agent`). The Agent Framework routes execution to the target agent. If a specialist determines it received a misrouted question, it can hand back to triage for re-routing.

### Agent Definitions

**Triage Agent** — Created from `AzureOpenAIResponsesClient.as_agent()` with routing instructions. No tools; its only job is intent classification and a handoff call.

**Web Agent** — Created from `AzureOpenAIResponsesClient.as_agent()` with multiple tools:
- `AzureOpenAIResponsesClient.get_web_search_tool()` — Bing-grounded web search for current information
- `MCPStreamableHTTPTool` — Microsoft Learn MCP server (`https://learn.microsoft.com/api/mcp`) for documentation search, page fetching, and code sample search
- `decode_microsoft_acronym` — Local `@ai_function` tool for instant acronym decoding (AKS, RBAC, M365, etc.)

**License Agent** — Created from `AzureAIAgentClient` which connects to a deployed Foundry agent. The deployed agent has its own instructions, tools, and knowledge base (Azure AI Search index). No local configuration needed beyond the agent name and project endpoint.

### Building the Workflow

```python
from agent_framework.orchestrations import HandoffBuilder

# Each agent is an Agent instance (either local or Foundry-backed)
triage = create_triage_agent(client)
web_agent = create_web_agent(client)
license_agent = create_license_agent(client, credential)  # may be None

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
```

Routing is **one-way** (triage → specialists only). Specialists answer to the best of their ability or politely decline off-topic questions — they never hand back to triage. A `_max_handoffs_termination(6)` safety net prevents loops.

The license agent is optional. If `AZURE_AI_LICENSE_AGENT_ID` is not set, the workflow runs with triage + web agent only. This allows gradual adoption.

### MCP Tool Integration

The web agent uses Microsoft Learn's public MCP server for trusted documentation access:

```python
from agent_framework import MCPStreamableHTTPTool

ms_learn_mcp = MCPStreamableHTTPTool(
    name="microsoft_learn",
    url="https://learn.microsoft.com/api/mcp",
    description="Official Microsoft Learn MCP Server",
    approval_mode="never_require",
    request_timeout=60,
)
```

This gives the agent access to three tools from a single MCP endpoint:
- `microsoft_docs_search` — Search official documentation
- `microsoft_docs_fetch` — Fetch full page content
- `microsoft_code_sample_search` — Find code samples with language filtering

### Connecting to Foundry-Deployed Agents

The license agent demonstrates how to use `AzureAIAgentClient` to connect to an agent that's already deployed in Azure AI Foundry:

```python
from agent_framework import Agent
from agent_framework.azure import AzureAIAgentClient

azure_ai_agent_client = AzureAIAgentClient(
    agent_name="unified-knowledge-agent-1",
    credential=async_credential,
    project_endpoint=os.getenv("AZURE_AI_PROJECT_ENDPOINT"),
    model_deployment_name=os.getenv("AZURE_AI_MODEL", "gpt-4.1"),
)

license_agent = Agent(
    azure_ai_agent_client,
    instructions="Answer licensing questions using your knowledge base. If the question is not about licensing, answer to the best of your ability.",
    name="license_agent",
    description="Handles Microsoft 365 licensing questions",
)
```

The deployed agent's own instructions, tools, and knowledge base are used directly — no local wrapper needed.

## Enterprise Observability

Building a multi-agent system without observability is like flying blind. You need to answer questions like: Which agent handled this request? How many handoffs occurred? Why did this request take 25 seconds? Where are the tokens going?

The bot uses [Agent Framework's built-in observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability?pivots=programming-language-python) which auto-instruments agents, chat clients, and tool executions — combined with custom span enrichment to capture routing decisions.

### Dual-Mode Tracing

A single `configure_telemetry()` function selects the right provider based on the environment:

| Mode | When | Setup | View Results |
|------|------|-------|-------------|
| **AI Toolkit** | `LOCAL_TRACING=true` | `configure_otel_providers(vs_code_extension_port=4317)` | VS Code AI Toolkit trace panel |
| **Azure Monitor** | Production | `configure_azure_monitor()` + `enable_instrumentation()` | Azure Portal → App Insights |

This is the entire telemetry configuration file:

```python
def configure_telemetry() -> bool:
    local_tracing = os.getenv("LOCAL_TRACING", "").lower() in ("true", "1", "yes")
    if local_tracing:
        return _configure_local()    # AI Toolkit OTLP on port 4317
    else:
        return _configure_azure_monitor()  # Pattern #3
```

**Local mode** uses Agent Framework's `configure_otel_providers()` to export spans to the AI Toolkit extension's OTLP collector. This gives you a visual trace viewer directly in VS Code while developing.

**Production mode** follows [Pattern #3 from the Agent Framework docs](https://learn.microsoft.com/en-us/agent-framework/agents/observability?pivots=programming-language-python#3-third-party-setup):

```python
from azure.monitor.opentelemetry import configure_azure_monitor
from agent_framework.observability import create_resource, enable_instrumentation

# 1. Let Azure Monitor set up its providers (traces, logs, metrics)
configure_azure_monitor(
    connection_string=connection_string,
    resource=create_resource(),
    logger_name="cross-tenant-bot",
    enable_live_metrics=True,
)
# 2. Activate Agent Framework instrumentation code paths
enable_instrumentation(enable_sensitive_data=False)
```

`configure_azure_monitor()` sets up the OpenTelemetry pipeline (exporters, processors, resource attributes). `enable_instrumentation()` activates the Agent Framework's code-path hooks that create spans for agents, chat calls, and tools. The order matters — Azure Monitor must be configured first so the Agent Framework's spans have somewhere to go.

> **Warning:** Do **not** set `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true`. It activates a separate instrumentor from `azure-ai-projects` that conflicts with Agent Framework's own instrumentation and causes `NonRecordingSpan` attribute errors at runtime.

### What Gets Auto-Instrumented

With no additional code, Agent Framework creates these spans and metrics:

**Spans** (visible in App Insights → Transaction Search):

| Span Name | What It Captures |
|-----------|------------------|
| `invoke_agent <agent_name>` | Top-level span per agent invocation (e.g., `invoke_agent triage`) |
| `chat <model_name>` | Each LLM call (e.g., `chat gpt-4.1`), with prompts/responses if `enable_sensitive_data=True` |
| `execute_tool <function_name>` | Tool invocations (e.g., `execute_tool web_search`, `execute_tool microsoft_docs_search`) |

**Metrics** (visible in App Insights → Metrics or via KQL on `customMetrics`):

| Metric | What It Measures |
|--------|-----------------|
| `gen_ai.client.token.usage` | Token consumption per request (input/output, with model and token type dimensions) |
| `gen_ai.client.operation.duration` | Duration of each chat operation (seconds) |
| `agent_framework.function.invocation.duration` | Duration of each tool execution (seconds) |

These appear automatically as nested spans. A single user message produces a waterfall like:

```
Teams Bot Agent Chat [triage → web_agent] (8200ms)
  ├── invoke_agent triage (1200ms)
  │    └── chat gpt-4.1 (1100ms)
  ├── invoke_agent web_agent (7000ms)
  │    ├── chat gpt-4.1 (800ms)
  │    ├── execute_tool microsoft_docs_search (2100ms)
  │    ├── chat gpt-4.1 (600ms)
  │    ├── execute_tool microsoft_docs_fetch (1500ms)
  │    └── chat gpt-4.1 (2000ms)
```

### Custom Span Enrichment

Auto-instrumentation captures what happened inside each agent, but it does not capture the *routing decision* — which agent was selected and why. The bot adds this context to a parent span wrapping the entire workflow:

```python
with tracer.start_as_current_span("Teams Bot Agent Chat", kind=SpanKind.CLIENT) as span:
    span.set_attribute("conversation.id", conversation_id)
    span.set_attribute("user.name", user_name)
    span.set_attribute("history.turns", len(chat_messages) - 1)

    result = await workflow.run(chat_messages)

    # Extract routing from handoff_sent events
    handoff_chain = []
    for event in result:
        if getattr(event, 'type', None) == "handoff_sent":
            data = event.data
            handoff_chain.append((data.source, data.target))
            span.add_event("handoff", {"from": data.source, "to": data.target})

    # Build route label: "triage → web_agent"
    if handoff_chain:
        route_parts = [handoff_chain[0][0]]
        for _, target in handoff_chain:
            route_parts.append(target)
        span.set_attribute("agent.route", " → ".join(route_parts))
        span.set_attribute("agent.handoff_count", len(handoff_chain))

    span.update_name(f"Agent Chat [{route_label}]")
```

This gives you these searchable attributes in App Insights:

| Attribute | Example | Purpose |
|-----------|---------|---------|
| `agent.route` | `triage → web_agent` | Routing chain for this request |
| `agent.handoff_count` | `1` | Number of routing hops |
| `agent.responding` | `web_agent` | Which agent produced the final answer |
| `conversation.id` | `a]chat;...` | Correlate spans within a conversation |

### Structured Logging

Python's `logging` module with `extra={}` fields is all you need. When Azure Monitor OpenTelemetry is configured, logs are automatically sent to Application Insights and `extra={}` fields become searchable `customDimensions`:

```python
logger.info("Agent response generated", extra={
    "conversation_id": conv_id,
    "agent_name": "web_agent",
    "response_time_ms": 1200,
    "tool_calls": 3,
})
```

Query in KQL:
```kusto
traces
| where customDimensions.agent_name == "web_agent"
| where toint(customDimensions.response_time_ms) > 1000
```

## Agent Evaluation

An agent that works today might break tomorrow — a model update changes routing behavior, a prompt tweak causes the triage agent to misclassify, or a tool starts returning unexpected formats. Evaluation provides the safety net.

The bot includes a comprehensive evaluation framework that tests agent quality using both custom local evaluators and Azure AI Foundry's cloud evaluators, supporting single-turn and multi-turn conversations.

### What Gets Evaluated

**Quality evaluators** measure whether responses are good:

| Evaluator | What It Checks |
|-----------|---------------|
| `builtin.coherence` | Logical flow and internal consistency |
| `builtin.fluency` | Grammar and readability |
| `builtin.relevance` | Response actually addresses the query |
| `builtin.groundedness` | Response supported by retrieved context (prevents hallucination) |

**Safety evaluators** catch harmful content:

| Evaluator | What It Checks |
|-----------|---------------|
| `builtin.violence` | Violent content or threats |
| `builtin.sexual` | Inappropriate sexual content |
| `builtin.self_harm` | Self-harm references |
| `builtin.hate_unfairness` | Hate speech and discriminatory content |

**Agent evaluators** measure tool-using behavior (the multi-agent-specific part):

| Evaluator | What It Checks |
|-----------|---------------|
| `builtin.tool_call_accuracy` | Overall tool call quality — right tool, right parameters |
| `builtin.tool_selection` | Agent picks the appropriate tool for the task |
| `builtin.tool_call_success` | Tool calls complete without errors |
| `builtin.tool_input_accuracy` | Parameters passed to tools are correct |
| `builtin.tool_output_utilization` | Agent correctly uses tool outputs in its response |
| `builtin.task_completion` | Agent completes the entire task end-to-end |

### Custom Evaluators

Beyond Foundry's built-in evaluators, the bot includes four custom evaluators for domain-specific quality:

- **ScopeComplianceEvaluator** — Verifies the bot correctly handles in-scope (Microsoft questions) vs. out-of-scope (non-Microsoft) queries by politely declining the latter
- **IntentRecognitionEvaluator** — Checks that questions about licensing are routed to the license agent and general questions to the web agent
- **ResponseQualityEvaluator** — Scores response completeness, accuracy, and formatting
- **MultiTurnContextEvaluator** — Tests whether the agent maintains conversation context across turns (e.g., "tell me about AKS" followed by "how does it compare to ECS?" — the agent should know "it" refers to AKS)

### Single-Turn vs. Multi-Turn Testing

**Single-turn tests** evaluate individual question-response pairs across categories: Microsoft in-scope, out-of-scope, content safety, and edge cases. Each test case in `test_data.json` has a query and expected behavior.

**Multi-turn tests** evaluate conversation flows where context matters. A multi-turn test sends a sequence of messages and verifies the agent maintains coherent state:

```json
{
  "name": "licensing_context_retention",
  "turns": [
    { "query": "What's included in M365 E5?" },
    { "query": "How does that compare to E3?" },
    { "query": "Which one supports Copilot?" }
  ]
}
```

The evaluation framework creates a shared agent client instance for multi-turn tests so conversation history is preserved across turns — exactly as it would be in a real Teams conversation.

### Running Evaluations

```bash
cd src

# Full evaluation suite with Foundry cloud logging
python -m app.eval.multi_agent_eval --log-to-foundry

# Include agent-specific evaluators (analyzes tool call traces — more expensive)
python -m app.eval.multi_agent_eval --log-to-foundry --include-agent-evals

# Single-turn only / multi-turn only
python -m app.eval.multi_agent_eval --log-to-foundry --single-turn-only
python -m app.eval.multi_agent_eval --log-to-foundry --multi-turn-only

# Filter by category
python -m app.eval.multi_agent_eval --log-to-foundry --category licensing
```

Results appear in **Azure AI Foundry Portal → Your Project → Evaluations** with per-evaluator scores, trends over time, and drill-down into individual responses. This makes it practical to run evaluations in CI/CD pipelines and fail builds if quality drops below thresholds.

## Monitoring with Azure Workbooks

Traces and logs are useful for investigating individual requests, but you also need a dashboard view for operational monitoring. The project includes a pre-built Azure Monitor Workbook with seven monitoring tabs.

### The Dashboard

| Tab | What It Shows | Key KQL Source |
|-----|---------------|----------------|
| **Health Overview** | Request volume, avg/P95 latency, failure rate as KPI tiles + timechart | `dependencies` table, `Agent Chat` spans |
| **Agent Routing** | Agent invocation counts, routing chain patterns, handoff distribution | `customDimensions['gen_ai.agent.name']`, `customDimensions['agent.route']` |
| **Token Usage** | Input/output tokens by model over time, totals grid | `customMetrics` where `name == 'gen_ai.client.token.usage'` |
| **Tool Performance** | Avg/P95 tool execution duration, call counts per tool | `customMetrics` where `name == 'agent_framework.function.invocation.duration'` |
| **Errors** | Error trend (logs + exceptions + failed calls), recent exceptions grid | Union of `traces`, `exceptions`, `dependencies` |
| **Conversation Drilldown** | Paste an `operation_Id` to see the full trace waterfall | Union of all tables filtered by `operation_Id` |
| **Slow Requests** | P50/P95 latency trends, top 20 slowest requests with routing info | `dependencies` table, percentile calculations |

All queries use a parameterized time range picker (1h / 4h / 24h / 7d / 30d). Tab switching uses `conditionalVisibility` on group items so only the active tab's queries execute.

### Deployment

Two options:

**Option A — Automated (ARM template):**
```powershell
.\scripts\deploy-bot.ps1
Deploy-Workbook
```

The `Deploy-Workbook` function reads the App Insights connection string from `.env`, resolves the resource ID across all resource groups, and deploys `scripts/workbook-template.json` via `az deployment group create`.

**Option B — Portal import:**
1. Navigate to your App Insights resource in Azure Portal
2. Go to **Workbooks** → **+ New** → **Advanced Editor**
3. Paste the contents of `scripts/workbook-gallery.json` and click **Apply**

### Alerting Recommendations

Beyond the dashboard, configure alerts for key thresholds:

- **Error rate**: > 5 failed `Agent Chat` dependencies in 5 minutes
- **Latency**: Average `Agent Chat` duration > 10,000ms over 5 minutes
- **Token budget**: Daily `gen_ai.client.token.usage` exceeds your cost threshold
- **Exception spike**: > 10 exceptions in 5 minutes

## Development Workflow

Building a multi-agent system requires a tight feedback loop. The bot separates authentication concerns from telemetry concerns using two independent environment variables:

| Variable | Controls | Values |
|----------|----------|--------|
| `LOCAL_DEBUG` | **Authentication** — whether to use UAMI or `az login` | `true` = `AzureCliCredential`, `false` = `ManagedIdentityCredential` |
| `LOCAL_TRACING` | **Telemetry destination** — where traces go | `true` = AI Toolkit (OTLP port 4317), `false` = Azure Monitor |

This separation is deliberate. You can mix and match:

| Scenario | LOCAL_DEBUG | LOCAL_TRACING | What Happens |
|----------|-----------|---------------|-------------|
| **Inner loop development** | `true` | `true` | Uses `az login` + AI Toolkit traces in VS Code |
| **Local with prod telemetry** | `true` | `false` | Uses `az login` + sends traces to App Insights |
| **Production (ACA)** | `false` | `false` | Uses UAMI + Azure Monitor |

### Inner Loop (Local Development)

1. Run `az login` to authenticate
2. Set `LOCAL_DEBUG=true` and `LOCAL_TRACING=true` in `.env`
3. Open VS Code AI Toolkit: **Cmd/Ctrl+Shift+P** → `AI Toolkit: Open Trace`
4. Run `python -m app` from `src/`
5. Send messages via the Bot Framework Emulator or Teams
6. View the full trace waterfall in AI Toolkit — every agent invocation, LLM call, and tool execution appears with timing and token counts

### Outer Loop (Azure Container Apps)

The `deploy-bot.ps1` script automates the full deployment cycle:

```powershell
. .\scripts\deploy-bot.ps1

Deploy-BotInfrastructure -ImageTag "v1"  # Full initial deploy
Redeploy-BotCode -ImageTag "v2"          # Code-only redeploy
Verify-BotDeployment                      # Health check
Get-BotLogs -Tail 100                     # View live logs
Deploy-Workbook                           # Deploy monitoring dashboard
```

The script forces `LOCAL_DEBUG=false` and `LOCAL_TRACING=false` for ACA deployments to ensure production uses UAMI and Azure Monitor.

### Evaluation as a Quality Gate

Run evaluations locally before deploying, or integrate them into CI/CD:

```bash
# Quick smoke test (single-turn only, local evaluators)
python -m app.eval.multi_agent_eval --single-turn-only

# Full suite with Foundry (before merging PRs)
python -m app.eval.multi_agent_eval --log-to-foundry --include-agent-evals
```

Track evaluation scores in the Foundry Portal over time. If coherence drops below 4.0 or task completion drops below 80%, investigate before deploying.

## Cross-Tenant Authentication

If your bot needs to serve users across organizational boundaries — a software vendor providing a Teams bot to customers, or a platform team deploying across subsidiary tenants — you need a cross-tenant authentication strategy. Microsoft deprecated multi-tenant bot creation in July 2025, but the architecture described below solves this cleanly using UAMI for bot authentication and Resource-Specific Consent (RSC) for Graph API access.

### Understanding the Deprecation

Microsoft's official documentation now states:

> Multi-tenant bot creation will be deprecated after July 31, 2025. Existing multi-tenant bots will continue to function, but new multi-tenant bot creation will no longer be supported after that date. To ensure continued support, use single-tenant or user-assigned managed identity going forward.

The deprecation applies specifically to the Azure Bot resource's authentication type. When creating an Azure Bot, you previously had three options:

1. **Multi-tenant** - Bot works in any Azure AD tenant (deprecated for new bots)
2. **Single-tenant** - Bot works only in one Azure AD tenant
3. **User-Assigned Managed Identity** - Bot authenticates using an Azure managed identity

With multi-tenant no longer available for new bots, UAMI becomes the recommended approach for new development.

### The Cross-Tenant Challenge

At first glance, UAMI appears to limit bots to single-tenant scenarios. A managed identity belongs to one Azure subscription in one tenant. How can this identity enable cross-tenant communication?

The answer lies in understanding what UAMI actually authenticates: the bot's communication with Azure Bot Framework, not the end-user interactions.

When a user in Tenant B sends a message to your bot hosted in Tenant A:

1. The message travels through Microsoft's Bot Framework Service
2. Bot Framework routes it to your bot's messaging endpoint
3. Your bot processes the message and sends a response
4. Bot Framework routes the response back to the user in Tenant B

The Bot Framework handles the cross-tenant routing transparently. Your bot's UAMI authentication proves your bot's identity to Bot Framework. It does not restrict which tenants can communicate with your bot.

However, if your bot needs to call Microsoft Graph API to access resources in Tenant B (such as reading channel messages), you need a separate authentication mechanism. This is where Resource-Specific Consent enters the picture.

### Identity Architecture

The solution uses two distinct identities:

#### Identity 1: User-Assigned Managed Identity (UAMI)

Purpose:
- Authenticate to Azure Bot Framework for sending/receiving messages
- Authenticate to Azure Key Vault for retrieving secrets
- No secrets stored in code or configuration

The UAMI is created in your home tenant (Tenant A) and assigned to your bot's compute resource (Azure Container Apps, App Service, etc.).

#### Identity 2: Multi-Tenant App Registration

Purpose:
- Authenticate to Microsoft Graph API in any tenant where the app is installed
- Uses client credentials flow with a client secret
- The secret is stored in Key Vault and accessed via UAMI

This is not a multi-tenant *bot*—it is a multi-tenant *app registration* used solely for Graph API access. The distinction matters: Microsoft deprecated multi-tenant bot authentication, not multi-tenant app registrations.

#### Resource-Specific Consent (RSC)

RSC is a Teams-specific authorization model that allows apps to request permissions scoped to individual teams or chats rather than requiring tenant-wide admin consent.

When a team owner installs your Teams app, they consent to the RSC permissions declared in your app manifest. These permissions apply only to that specific team. No global admin involvement is required.

RSC permissions include:

- `ChannelMessage.Read.Group` - Read messages in a team's channels
- `TeamSettings.Read.Group` - Read team settings
- `TeamMember.Read.Group` - Read team membership
- `ChannelSettings.Read.Group` - Read channel settings

This model aligns well with cross-tenant scenarios. Each tenant's team owners control which teams grant access to your bot.

#### When Is Graph API Access Actually Needed?

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

### Authentication Flow

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

### Implementation Details

#### Teams App Manifest

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

#### Azure AD App Configuration

The multi-tenant app registration requires minimal configuration:

- **Supported account types**: Accounts in any organizational directory (Multi-tenant)
- **API Permissions**: None required in Azure AD portal—RSC permissions are granted through Teams
- **Client Secret**: Generated and stored in Key Vault

A critical point: Do not add Graph API permissions (like `ChannelMessage.Read.All`) to this app registration. Adding Azure AD permissions causes Graph API to use those instead of RSC permissions, breaking the per-team scoping model.

#### Acquiring Tokens for External Tenants

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

#### Extracting Team and Channel IDs

A critical detail for Graph API calls: the `team_id` must be the **M365 Group ID** (a GUID), not the channel-style `19:xxx@thread.tacv2` format that appears in some activity fields.

The `conversation.id` in channel activities contains the Group ID:
```
19:abc123@thread.tacv2;groupId=12345678-1234-1234-1234-123456789abc;tenantId=...
```

Extract both IDs from `conversation.id`:

```python
import re

def extract_team_channel_ids(activity) -> tuple:
    """Extract team (M365 Group ID) and channel IDs from a Teams activity."""
    conv_id = activity.conversation.id or ''
    
    # Extract groupId (M365 Group ID) - required for Graph API
    group_match = re.search(r'groupId=([a-f0-9-]+)', conv_id, re.IGNORECASE)
    team_id = group_match.group(1) if group_match else None
    
    # Extract channel_id (the 19:xxx@thread.tacv2 part)
    channel_match = re.search(r'(19:[^;]+)', conv_id)
    channel_id = channel_match.group(1) if channel_match else None
    
    return team_id, channel_id
```

**Warning:** Do not use `channel_data.team.id` or `channel_data.teamsTeamId`—these may return the channel-style ID, which causes 403 errors when used with Graph API.

#### Reading Channel Messages with RSC

With RSC permissions, you can read channel messages without user authentication:

```python
from urllib.parse import quote

async def get_channel_messages(team_id: str, channel_id: str, tenant_id: str):
    """Read channel messages using RSC permissions."""
    
    token = await get_app_token(tenant_id)
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # URL encode the channel_id (contains special characters like @ and :)
    encoded_channel_id = quote(channel_id, safe='')
    
    # Beta endpoint required for RSC channel message access
    # team_id must be M365 Group ID (GUID), not 19:xxx format
    url = f"https://graph.microsoft.com/beta/teams/{team_id}/channels/{encoded_channel_id}/messages"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            return data.get("value", [])
```

Note the use of the beta endpoint. As of this writing, RSC-based channel message access requires the beta API. Also note the URL encoding of `channel_id` to handle special characters.

#### Fetching Message Replies

The Graph API returns only top-level messages from the messages endpoint. Replies require a separate call:

```python
async def get_message_replies(team_id: str, channel_id: str, message_id: str, tenant_id: str):
    """Fetch replies to a specific message."""
    
    token = await get_app_token(tenant_id)
    
    url = f"https://graph.microsoft.com/beta/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"
    
    # ... make request and return replies
```

### Common Pitfalls

#### RSC Permissions Not Being Granted

Symptoms: Graph API returns 403 Forbidden with permission errors.

Causes and solutions:

1. **App ID mismatch**: The `webApplicationInfo.id` in your manifest must match the app ID your bot uses for Graph API calls.

2. **Azure AD permissions conflict**: If your app registration has any Graph API permissions configured in Azure AD (like `Team.ReadBasic.All`), Graph uses those instead of RSC. Remove all Graph permissions from the Azure AD app.

3. **Manifest not updated**: After changing `webApplicationInfo.id`, you must republish the Teams app and reinstall it in each team.

4. **Tenant RSC policy**: The target tenant may have RSC disabled. Check Teams Admin Center settings.

5. **Wrong team_id format**: The Graph API requires the M365 Group ID (a GUID like `12345678-1234-1234-1234-123456789abc`), not the channel-style ID (`19:xxx@thread.tacv2`). Extract `groupId` from `conversation.id` rather than using `channel_data.team.id`.

#### Verifying RSC Permissions

Use Graph Explorer to check if RSC permissions are granted for a team:

```
GET https://graph.microsoft.com/beta/teams/{team-id}/permissionGrants
```

The response should list each RSC permission granted to your app.

#### Token Acquisition Failing for External Tenants

Ensure your multi-tenant app registration is configured for "Accounts in any organizational directory." Single-tenant app registrations cannot acquire tokens for other tenants.

#### Beta Endpoint Required for RSC

RSC-based channel message access currently requires the Graph API beta endpoint (`graph.microsoft.com/beta`). The v1.0 endpoint does not support RSC for channel messages. If you're getting permission errors with v1.0, switch to the beta endpoint.

## Security Considerations

This architecture provides several security benefits:

1. **No secrets in code**: UAMI authenticates the bot to Bot Framework and Key Vault without credentials. `DefaultAzureCredential` handles Azure OpenAI and Foundry access, inheriting the UAMI identity in production — no additional secrets needed.

2. **Managed identity throughout**: In production, UAMI is the single identity for Bot Framework, Key Vault, and Azure AI services. Locally, `az login` provides the same access pattern via `DefaultAzureCredential`.

3. **Per-team scoping (cross-tenant)**: RSC permissions apply only to teams where the app is installed. Unlike tenant-wide permissions, a compromised token cannot access other teams in Tenant B.

4. **Team owner control (cross-tenant)**: Team owners in Tenant B decide whether to install your app. Global admins are not required for RSC consent.

5. **Credential rotation (cross-tenant)**: Rotating the Graph API client secret requires only updating Key Vault in Tenant A. No application redeployment needed.

## Conclusion

This article walked through the complete lifecycle of building a production multi-agent Teams bot — from orchestration design through observability, evaluation, monitoring, and deployment.

**Multi-agent orchestration** is the core of the system. HandoffBuilder composes a triage agent with specialist agents, each having focused instructions and appropriate tools. The triage agent classifies intent; the web agent searches Bing, queries Microsoft Learn via MCP, and decodes acronyms; the license agent connects to a Foundry-deployed knowledge base. One-way routing (triage → specialists only) with a handoff termination safety net keeps the system predictable.

**Enterprise observability** makes the system debuggable and monitorable. Agent Framework's built-in instrumentation creates `invoke_agent`, `chat`, and `execute_tool` spans automatically. Custom enrichment on the parent span captures routing decisions (`agent.route`, `agent.handoff_count`). Dual-mode tracing sends spans to AI Toolkit locally and Azure Monitor in production — same code, different destination.

**Agent evaluation** provides a quality safety net. Custom evaluators check domain-specific behavior (scope compliance, intent recognition). Foundry's built-in evaluators measure response quality, safety, and agent-specific behavior (tool call accuracy, task completion). Multi-turn tests verify conversation context retention. Running evaluations before deployment catches regressions before users do.

**Monitoring with Azure Workbooks** gives the operations team a dashboard. Seven tabs covering health, routing, tokens, tools, errors, conversation drilldown, and slow requests — all driven by KQL queries against the telemetry the bot already produces.

**The development workflow** ties it all together. `LOCAL_DEBUG` and `LOCAL_TRACING` separate authentication from telemetry, enabling distinct development scenarios. The inner loop uses AI Toolkit for instant trace visibility. The outer loop deploys to Azure Container Apps with full Azure Monitor telemetry. Evaluations serve as quality gates between the two.

**Cross-tenant authentication** extends the bot across organizational boundaries. UAMI authenticates the bot to Bot Framework without secrets in code. A separate multi-tenant app registration handles Graph API calls across tenants. RSC provides per-team authorization controlled by team owners, not global admins.

The key insight is that these concerns reinforce each other. Observability data flows into workbook dashboards. Evaluation results help you interpret what the traces mean. The dual-mode tracing design ensures you see the same span structure locally and in production. And the authentication foundation — whether single-tenant or cross-tenant — makes all of this work securely.

The complete reference implementation — with deployment automation, multi-agent orchestration, evaluation framework, monitoring workbook, and detailed documentation — is available as an open-source accelerator:

**Repository**: https://github.com/divssheth/cross-tenant-bot

**Documentation**:
- [Multi-Agent Orchestration Guide](docs/MULTI_AGENT_ORCHESTRATION.md) — HandoffBuilder workflow, agent definitions, tool types
- [Observability Guide](docs/OBSERVABILITY.md) — Tracing, logging, KQL queries, dashboards, alerts
- [Evaluation Guide](docs/EVALUATION_GUIDE.md) — Evaluation setup, custom evaluators, Foundry SDK
- [KQL Cheatsheet](docs/KQL_CHEATSHEET.md) — Copy-paste queries for Application Insights

**Microsoft References**:
- [Azure Bot UAMI Registration](https://learn.microsoft.com/en-us/azure/bot-service/bot-service-quickstart-registration?view=azure-bot-service-4.0&tabs=userassigned)
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- [Agent Framework Observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability?pivots=programming-language-python)
- [Azure AI Evaluation SDK](https://learn.microsoft.com/en-us/azure/ai-studio/how-to/evaluate-sdk)

---

*Divyesh Sheth is a software engineer focused on Microsoft 365 platform development.*
