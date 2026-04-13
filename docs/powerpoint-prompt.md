# PowerPoint Generation Prompt

Copy everything below this line and paste into Copilot to generate the deck.

---

Create a professional PowerPoint presentation titled "Building Multi-Agent Bots with M365 Agents SDK + Microsoft Agent Framework". This is a 60-minute technical talk for developers and architects. Use a modern Microsoft/Azure-themed design with dark blue (#0078D4) accents. The narrative thread is: "Here's how to build production multi-agent bots in Teams — and it's easier than you think."

Generate the following slides:

---

## Slide 1: Title Slide
**Title**: Building Multi-Agent Bots with M365 Agents SDK + Microsoft Agent Framework
**Subtitle**: Two frameworks, three agents, zero secrets, full observability
**Footer**: 60-minute technical deep-dive

---

## Slide 2: Agenda
**Title**: What We'll Cover
**Bullet list**:
1. Why Multi-Agent? (5 min)
2. The Two Frameworks — Where Each Plays (8 min)
3. Auth & Identity — UAMI in Action (8 min)
4. Multi-Agent Architecture (12 min)
5. Observability & Monitoring (10 min)
6. Evaluation (5 min)
7. Deployment & Cross-Tenancy (10 min)
8. Learnings & Close (2 min)

---

## Slide 3: The Problem with Single-Agent Bots
**Title**: Why Multi-Agent?
**Left column — "Single Agent"** (with a red X or warning icon):
- One prompt, all the tools
- Bloated system prompts
- Conflicting tool behaviors
- Can't evaluate specific capabilities
- Works for demos, fails in production

**Right column — "Multi-Agent"** (with a green checkmark):
- Triage agent classifies intent
- Specialist agents handle domains
- Focused tools per agent
- Independent evaluation per agent
- Domain decomposition = production-ready

**Speaker notes**: Start with the pain. Most teams begin with one agent and hit a wall when they need different tools, instructions, and evaluation criteria per domain.

---

## Slide 4: Architecture Overview
**Title**: System Architecture
**Content**: Full-width placeholder for the architecture diagram image. Label it "[Insert architecture-overview.png]"
**Caption**: Triage Agent routes to Web Agent (Bing + MCP) or License Agent (Foundry knowledge base). Hosted in Azure Container Apps.
**Speaker notes**: This is the reference diagram — we'll zoom into each piece. M365 Agents SDK handles Teams plumbing on the left. Agent Framework handles AI orchestration in the middle. Azure services on the right.

---

## Slide 5: Two Frameworks, One Bridge Point
**Title**: M365 Agents SDK + Microsoft Agent Framework
**Content**: A table with two columns:

| Responsibility | M365 Agents SDK | MS Agent Framework |
|---|---|---|
| Receives Teams message | ✓ | |
| JWT / UAMI auth | ✓ | |
| Message handlers (@message) | ✓ | |
| Agent creation (as_agent()) | | ✓ |
| Tool execution | | ✓ |
| Handoff routing | | ✓ |
| Auto-instrumentation | | ✓ |
| LLM calls | | ✓ |
| Sends response to Teams | ✓ | |

**Callout box at bottom**: "They compose at one clean bridge point: get_agent_client()"
**Speaker notes**: M365 SDK is the message bus. Agent Framework is the intelligence. Show the AgentApplication constructor (3 lines) and the bridge call.

---

## Slide 6: M365 Agents SDK — The Teams Plumbing
**Title**: M365 Agents SDK — 3 Lines to Teams
**Content**: Code snippet block:
```
AGENT_APP = AgentApplication(
    auth_config=auth_config,
    adapter=CloudAdapter(auth_config),
    storage=MemoryStorage(),
)
```
**Bullet points below**:
- UAMI authentication (no passwords)
- Decorator-based handlers: @AGENT_APP.message(regex)
- Health endpoints, JWT validation, channel routing — all built in
**Speaker notes**: Emphasize simplicity. Three lines and the bot talks to Teams.

---

## Slide 7: The Bridge — SDK to Agent Framework
**Title**: The Bridge Point
**Content**: Code snippet block:
```
agent = get_agent_client()
response = await agent.chat(
    message=user_message,
    conversation_id=conversation_id,
    user_name=user_context.user_name,
)
```
**Callout**: "M365 SDK receives the message. One function call later, Agent Framework takes over."
**Speaker notes**: This is the most important architectural slide. One clean handoff between frameworks.

---

## Slide 8: Auth & Identity — UAMI
**Title**: UAMI — Zero Secrets Architecture
**Content**: Three environment variables shown prominently:
```
AZURE_CLIENT_ID=<uami-client-id>        # This IS the bot identity
AZURE_TENANT_ID=<home-tenant>
MICROSOFT_APP_ID=<same as AZURE_CLIENT_ID>  # Same value!
```
**Bullet points**:
- UAMI = Managed identity assigned to Container App
- Authenticates to: Bot Service, Key Vault, Azure OpenAI
- Zero passwords in code or environment
- Local dev uses az login, production uses UAMI
**Speaker notes**: Traditional bots used MICROSOFT_APP_PASSWORD. UAMI eliminates that entirely. The container has an identity, not a password.

---

## Slide 9: Credential Selection Pattern
**Title**: Two Paths, Zero Secrets
**Content**: Code snippet:
```
if local_debug:
    return AzureCliCredential()           # az login session
elif self.managed_identity_client_id:
    return ManagedIdentityCredential(     # UAMI in production
        client_id=self.managed_identity_client_id
    )
else:
    return DefaultAzureCredential()
```
**Speaker notes**: Simple branching. No if/else for secrets anywhere in the codebase.

---

## Slide 10: Multi-Agent Architecture — The Agents
**Title**: Three Agents, Three Patterns
**Layout**: Three columns, one per agent.

**Column 1 — Triage Agent** (blue accent):
- Routing only, no tools
- Decides: web question or licensing question?
- Instructions-only agent

**Column 2 — Web Agent** (green accent):
- @ai_function: decode_microsoft_acronym (local Python)
- Built-in: Bing web search
- MCP: Microsoft Learn server
- "Three tool types in 8 lines"

**Column 3 — License Agent** (purple accent):
- Retrieved from Azure AI Foundry
- Own knowledge base, own instructions
- Reused, not recreated

**Speaker notes**: Each agent has focused tools and focused evaluation. This is the power of decomposition.

---

## Slide 11: Web Agent — Three Tool Types
**Title**: Three Tool Types in 8 Lines
**Content**: Code snippet:
```
tools = [
    decode_microsoft_acronym,                       # @ai_function (local Python)
    AzureOpenAIResponsesClient.get_web_search_tool(), # Built-in (Bing)
    MCPStreamableHTTPTool(                          # MCP (Microsoft Learn)
        name="microsoft_learn",
        url="https://learn.microsoft.com/api/mcp",
    ),
]
```
**Speaker notes**: A local function, a platform built-in, and an external MCP server — all composed seamlessly.

---

## Slide 12: License Agent — Foundry-Deployed
**Title**: Reuse Agents from Azure AI Foundry
**Content**: Code snippet:
```
provider = AzureAIProjectAgentProvider(
    project_endpoint=endpoint, credential=async_credential
)
agent = await provider.get_agent(name="unified-knowledge-agent-1")
```
**Callout**: "Don't recreate — reuse. This agent has its own knowledge base and instructions in Foundry."
**Speaker notes**: Foundry agents can be managed independently by different teams.

---

## Slide 13: Orchestration — HandoffBuilder
**Title**: Wiring Agents with HandoffBuilder
**Content**: Code snippet:
```
builder = (
    HandoffBuilder(
        name="ms-expert-orchestration",
        participants=participants,
        termination_condition=_max_handoffs_termination(6),
    )
    .with_start_agent(triage)
    .add_handoff(triage, triage_targets)
)
workflow = builder.build()
```
**Key points below**:
- Triage starts, hands off to specialists
- One-way routing prevents infinite loops
- Six handoffs max as safety net
**Speaker notes**: Five lines of wiring. Autonomous mode with Foundry agents caused infinite loops — one-way is simpler and reliable.

---

## Slide 14: Fresh Workflow Pattern
**Title**: Create Agents Once, Fresh Workflow Per Message
**Content**: Code snippet:
```
await self._ensure_agents_created()  # Agents created ONCE (expensive)
workflow = self._create_workflow()    # Fresh workflow per message (cheap)
result = await workflow.run(chat_messages)
```
**Warning callout (red/orange box)**: "If you reuse a workflow across messages, you get stale 'No tool output found' errors."
**Speaker notes**: Hard-won lesson. Agents are expensive (HTTP calls to Foundry). Workflows are cheap but stateful. Always fresh workflow.

---

## Slide 15: Observability — Dual-Mode Telemetry
**Title**: One Instrumentation, Two Destinations
**Content**: Code snippet:
```
if local_tracing:
    configure_otel_providers(vs_code_extension_port=4317)  # AI Toolkit
else:
    configure_azure_monitor(connection_string=connection_string)
    enable_instrumentation(enable_sensitive_data=False)
```
**Two-column layout below**:
- **Local**: AI Toolkit in VS Code (port 4317)
- **Production**: Application Insights

**Warning callout**: "configure_azure_monitor() MUST come before enable_instrumentation()"
**Speaker notes**: Same instrumentation code, two destinations. Order matters — configure destination before enabling spans.

---

## Slide 16: What You Get for Free
**Title**: Agent Framework Auto-Instrumentation
**Bullet list with icons**:
- invoke_agent triage — agent routing spans
- chat gpt-4.1 — LLM call spans
- execute_tool web_search — tool execution spans
- Token usage per model — auto metrics
- LLM call duration — auto metrics
- Tool execution latency — auto metrics
**Callout**: "Zero code. All automatic."
**Speaker notes**: Agent Framework auto-instruments everything. You add business context on top.

---

## Slide 17: Custom Span Enrichment
**Title**: Add Business Context to Traces
**Content**: Code snippet:
```
with tracer.start_as_current_span("Teams Bot Agent Chat") as span:
    span.set_attribute("agent.route", "triage → web_agent")
    span.set_attribute("agent.handoff_count", len(handoff_chain))
    span.add_event("handoff", {"from": source, "to": target})
```
**Speaker notes**: Agent Framework gives you the spans. You add which route was taken, how many handoffs, which conversation.

---

## Slide 18: Live Demo
**Title**: 🎬 Live Demo — End-to-End Trace
**Content**: Large centered text:
1. Send a message in Teams
2. Switch to AI Toolkit / App Insights
3. Show trace waterfall: user message → triage → web_agent → LLM → tools
**Callout**: "Every decision the system made, visible in one trace."
**Speaker notes**: This is the one live demo moment. Show the full trace waterfall.

---

## Slide 19: Dashboards & KQL
**Title**: Pre-Built Dashboards
**Bullet points**:
- Azure Workbook with 7 tabs: Health, Agent Routing, Token Usage, Tool Performance, Errors, Conversation Drilldown, Slow Requests
- KQL cheat sheet for ad-hoc queries
- Agent routing summary, token usage by model
**Speaker notes**: Reference KQL_CHEATSHEET.md and scripts/workbook-template.json.

---

## Slide 20: Evaluation
**Title**: Evaluate Routing, Not Just Responses
**Three-column layout**:

**Column 1 — Custom Evaluators**:
- RoutingAccuracyEvaluator (1.0 = correct agent)
- HandoffEfficiencyEvaluator (penalizes loops)
- CrossAgentContextEvaluator (context retention)

**Column 2 — Foundry Built-in**:
- Coherence
- Fluency
- Relevance
- Task completion

**Column 3 — Test Categories**:
- microsoft_in_scope
- licensing
- out_of_scope
- greeting

**Speaker notes**: Multi-agent systems need multi-agent metrics. Routing accuracy is the most important — did triage send it to the right specialist?

---

## Slide 21: Deployment with UAMI
**Title**: Deployment — One Identity, Zero Secrets
**Bullet list**:
- ACR build (no local Docker needed)
- Container App with --user-assigned UAMI
- --registry-identity for ACR pull (UAMI, no ACR passwords)
- Environment variables from .env, forced LOCAL_DEBUG=false
**Callout**: "UAMI does everything: Bot Service, ACR, Key Vault, Azure OpenAI."
**Speaker notes**: Reference scripts/deploy-bot.ps1.

---

## Slide 22: Cross-Tenant Architecture
**Title**: Cross-Tenant Auth Flow
**Content**: Full-width placeholder for diagram. Label it "[Insert cross-tenant-auth diagram]"
**Caption**: Home Tenant (Contoso) hosts the bot. Target Tenant (Fabrikam) has the users.
**Speaker notes**: Walk through the 8 numbered steps. This is the most complex slide — take it slowly.

---

## Slide 23: Cross-Tenant Flow — Step by Step
**Title**: The 8-Step Cross-Tenant Flow
**Numbered list** (use animation to reveal one at a time):
1. **Admin consent** — Multi-tenant App Reg in Contoso → Service Principal auto-created in Fabrikam
2. **Teams admin installs** — Bot app installed per-team → RSC permissions (ChannelMessage.Read.Group)
3. **Teams message** — User in Fabrikam sends message → routes to Bot Service
4. **Route (UAMI auth)** — Bot Service routes to Container App, authenticated via UAMI
5. **Agent processing** — Container App sends to Azure OpenAI / Foundry
6. **Get secret (UAMI)** — Container App uses UAMI to retrieve client secret from Key Vault
7. **Client credentials** — Container App uses secret for client credentials flow to Fabrikam's Service Principal
8. **Graph API** — Reads channels via Service Principal (/beta endpoint, RSC permissions)

**Speaker notes**: Two hops, two identities. UAMI gets the secret, then the secret is used for client credentials to the other tenant.

---

## Slide 24: UAMI vs App Registration
**Title**: The Critical Distinction
**Content**: Two-column comparison table with strong visual contrast:

| | UAMI | Multi-Tenant App Reg |
|---|---|---|
| **Purpose** | Bot identity → Bot Service, Key Vault, OpenAI | Graph API identity → client credentials to target tenant |
| **Scope** | Home tenant only | Cross-tenant |
| **Secrets** | None. Zero. Ever. | Client secret stored in Key Vault |
| **Used for** | Authentication within Contoso | Reaching into Fabrikam |

**Red callout box**: "These are COMPLETELY SEPARATE identities for COMPLETELY SEPARATE purposes. AZURE_CLIENT_ID = MICROSOFT_APP_ID — same value, different roles. This naming overlap caused hours of debugging."
**Speaker notes**: This was the team's biggest confusion. Be very explicit about the separation.

---

## Slide 25: Graph API with RSC
**Title**: RSC — Reading Channels Cross-Tenant
**Content**: Architecture flow shown as text:
```
1. UAMI → Key Vault (get client secret)
2. Client secret → Client credentials flow to TARGET tenant
3. Token → Graph API /beta endpoint
4. RSC permissions → Read channel messages
```
**Warning callouts (red)**:
- "RSC requires /beta endpoint — not v1.0"
- "Adding Graph API permissions in Azure AD OVERWRITES RSC consent"
- "Remove all AAD app permissions except User.Read"
**Speaker notes**: These RSC gotchas cost the team significant debugging time.

---

## Slide 26: Rapid-Fire Learnings
**Title**: Top Learnings
**Four items with icons**:
1. 🔄 **Fresh workflow, cached agents** — or you get stale "No tool output found" errors
2. 📊 **Instrumentation order** — configure_azure_monitor() before enable_instrumentation(), plus AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true
3. 🆔 **Teams ID formats** — Graph needs GUIDs, not 19:xxx thread IDs. Built TeamMappingCache to solve it.
4. ⚠️ **RSC gotcha** — /beta endpoint only. Graph permissions overwrite RSC. Remove all AAD permissions except User.Read.

**Speaker notes**: Rapid-fire — spend about 15 seconds on each one.

---

## Slide 27: Closing
**Title**: Go Build Yours
**Large centered text**: "Two frameworks, three agents, zero secrets, full observability."
**Subtitle**: "The hard parts were auth and identity, not the AI."
**Bullet points**:
- M365 Agents SDK → Teams plumbing
- Microsoft Agent Framework → AI orchestration
- UAMI → Zero secrets
- HandoffBuilder → Multi-agent in 5 lines
- Auto-instrumentation → Observability for free

---

## Slide 28: Resources / Q&A
**Title**: Resources & Q&A
**Content**: Placeholder for repo link, documentation links, and contact info.
