# Observability Guide

Comprehensive guide to tracing, logging, evaluations, and monitoring for the Cross-Tenant Multi-Agent Teams Bot.

## Table of Contents

- [Overview](#overview)
- [Quick Setup](#quick-setup)
- [Dual-Mode Tracing](#dual-mode-tracing)
- [Auto-Instrumented Spans & Metrics](#auto-instrumented-spans--metrics)
- [Structured Logging](#structured-logging)
- [Distributed Tracing](#distributed-tracing)
- [Agent Evaluations](#agent-evaluations)
- [KQL Queries & Dashboards](#kql-queries--dashboards)
- [Alerts & Monitoring](#alerts--monitoring)
- [Environment Variables](#environment-variables)
- [Best Practices Checklist](#best-practices-checklist)

---

## Overview

The bot uses **Agent Framework's built-in observability** ([docs](https://learn.microsoft.com/en-us/agent-framework/agents/observability?pivots=programming-language-python)) which auto-instruments agents, chat clients, and tool executions. Two deployment modes share the same `configure_telemetry()` entry point:

| Mode | When | How | View Results |
|------|------|-----|-------------|
| **AI Toolkit (Local)** | `LOCAL_TRACING=true` | `configure_otel_providers(vs_code_extension_port=4317)` | VS Code AI Toolkit trace viewer |
| **Azure Monitor (Production)** | `APPLICATIONINSIGHTS_CONNECTION_STRING` set | `configure_azure_monitor()` + `enable_instrumentation()` | Azure Portal → Application Insights |

> **Note:** `LOCAL_TRACING` controls where traces go. `LOCAL_DEBUG` controls authentication (skip UAMI for local dev). You can use `LOCAL_DEBUG=true` + `LOCAL_TRACING=false` to debug locally while sending traces to App Insights.

Both modes use the same `configure_telemetry()` entry point in [`src/app/trace_config.py`](../src/app/trace_config.py) — the function auto-selects based on your environment.

### Architecture

```
┌─────────────────────┐   OpenTelemetry   ┌─────────────────────┐
│  Cross-Tenant Bot   │ ────────────────► │  Azure Application  │
│  (Multi-Agent)      │   Traces / Logs   │      Insights       │
└─────────────────────┘                   └─────────────────────┘
         │                                          │
         ▼                                          ▼
   ┌───────────────┐                    ┌─────────────────────┐
   │  Foundry      │                    │  Log Analytics       │
   │  Evaluations  │                    │  Workspace (KQL)     │
   └───────────────┘                    └─────────────────────┘
```

### Required Packages

| Package | Purpose |
|---------|---------|
| `azure-monitor-opentelemetry` | Production telemetry to Azure Monitor |
| `opentelemetry-api` / `opentelemetry-sdk` | Tracing spans and attributes |
| `agent-framework-core` | Built-in observability (auto-instruments agents, chat, tools) |
| `azure-ai-evaluation` | Foundry evaluation SDK |

---

## Quick Setup

### Local Development (AI Toolkit)

1. Install the [AI Toolkit extension](https://marketplace.visualstudio.com/items?itemName=ms-windows-ai-studio.windows-ai-studio) in VS Code
2. Open the trace collector: **Cmd/Ctrl+Shift+P** → `AI Toolkit: Open Trace` (or `ai-mlstudio.tracing.open`)
3. Set `LOCAL_DEBUG=true` and `LOCAL_TRACING=true` in your `.env`
4. Run the bot — traces appear in the AI Toolkit panel

### Production (Azure Monitor)

1. Create an Application Insights resource in Azure
2. Set `APPLICATIONINSIGHTS_CONNECTION_STRING` in your environment
3. Set `LOCAL_TRACING=false` (or omit it) and `LOCAL_DEBUG=false`
4. Deploy — Agent Framework auto-creates `invoke_agent`, `chat`, and `execute_tool` spans in App Insights

---

## Dual-Mode Tracing

The [`trace_config.py`](../src/app/trace_config.py) module selects the telemetry provider automatically:

```python
from app.trace_config import configure_telemetry

# Called once at startup in __main__.py
# - LOCAL_TRACING=true → Agent Framework tracing (AI Toolkit, port 4317)
# - Otherwise → Azure Monitor (configure_azure_monitor + enable_instrumentation)
configure_telemetry()
```

### How It Works

```python
def configure_telemetry() -> bool:
    local_tracing = os.getenv("LOCAL_TRACING", "").lower() in ("true", "1", "yes")
    if local_tracing:
        ok = _configure_local()
    else:
        ok = _configure_azure_monitor()
    ...
```

**Local mode** — uses `configure_otel_providers(vs_code_extension_port=4317)` to export to the AI Toolkit OTLP collector.

**Production mode** — follows [Pattern #3 from the Agent Framework docs](https://learn.microsoft.com/en-us/agent-framework/agents/observability?pivots=programming-language-python#3-third-party-setup):

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

> **Warning:** Do NOT set `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING=true` — it activates a separate instrumentor from `azure-ai-projects` that conflicts with Agent Framework's own and causes `NonRecordingSpan` attribute errors at runtime.

---

## Auto-Instrumented Spans & Metrics

Agent Framework automatically creates the following with **no extra code needed**:

### Spans

| Span Name | What It Captures |
|-----------|------------------|
| `invoke_agent <agent_name>` | Top-level span for each agent invocation (e.g., `invoke_agent triage`) |
| `chat <model_name>` | LLM calls (e.g., `chat gpt-4.1`). Includes prompts/responses if `enable_sensitive_data=True` |
| `execute_tool <function_name>` | Tool invocations (e.g., `execute_tool web_search`). Includes args/results if sensitive data enabled |

### Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `gen_ai.client.operation.duration` | Histogram | Duration of each chat operation (seconds) |
| `gen_ai.client.token.usage` | Histogram | Token usage per request (input/output) |
| `agent_framework.function.invocation.duration` | Histogram | Duration of each tool execution (seconds) |

### Custom Span Attributes

The bot adds context to the parent `Teams Bot Agent Chat` span in `foundry_agent_client.py`:

| Attribute | Source | Purpose |
|-----------|--------|---------|
| `agent.id` | Agent config | Identify the bot agent |
| `agent.route` | Handoff events | Show routing chain (e.g., `triage → web_agent`) |
| `agent.handoff_count` | Handoff events | Number of routing hops |
| `agent.responding` | Output event | Which agent produced the final answer |
| `conversation.id` | Teams activity | Correlate spans within a conversation |
| `user.name` | Teams activity | Identify the requesting user |
| `response.length` | Agent output | Monitor response sizes |

---

## Structured Logging

Use Python's `logging` module with `extra={}` for searchable context in App Insights:

```python
import logging
logger = logging.getLogger("cross-tenant-bot")

# Basic log (appears in App Insights → traces table)
logger.info("Processing request")

# Structured log with searchable dimensions
logger.info(
    "Agent response generated",
    extra={
        "conversation_id": conv_id,
        "agent_name": "web_agent",
        "response_time_ms": 1200,
        "tool_calls": 3,
    }
)
```

In App Insights, `extra={}` fields become `customDimensions`:

```kusto
traces
| where customDimensions.agent_name == "web_agent"
| where toint(customDimensions.response_time_ms) > 1000
```

### Logging Configuration

The [`log_config.py`](../src/app/log_config.py) module configures:

- **App logger** (`cross-tenant-bot`) at `INFO` level
- **Azure/OpenTelemetry SDK loggers** at `WARNING` to reduce noise
- Structured format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`

> **Important:** Call `configure_telemetry()` BEFORE `configure_logging()` so Azure Monitor captures log output.

---

## Distributed Tracing

### Nested Spans

Create spans to track individual operations within a request:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def handle_user_message(message: str, conversation_id: str):
    with tracer.start_as_current_span("handle_user_message") as span:
        span.set_attribute("conversation.id", conversation_id)

        # Child span for agent routing
        with tracer.start_as_current_span("agent_routing") as route_span:
            route_span.set_attribute("agent.id", "triage")
            agent = route_to_agent(message)

        # Child span for agent execution
        with tracer.start_as_current_span("agent_execution") as exec_span:
            exec_span.set_attribute("agent.id", agent.name)
            response = await agent.run(message)

        return response
```

In App Insights, nested spans appear as a **waterfall view** under Transaction Search:

```
handle_user_message (1200ms)
  ├── agent_routing (50ms)
  └── agent_execution (1150ms)
       ├── llm_completion (800ms)
       └── tool_call: web_search (350ms)
```

### Agent Framework Auto-Instrumentation

The Agent Framework automatically creates spans for:
- `ChatClient.create_response` — LLM calls
- `Agent.run` — Agent execution
- `Workflow.run` — Orchestration passes
- Tool invocations (web search, MCP, etc.)

No extra code needed — just ensure telemetry is configured at startup.

---

## Agent Evaluations

The evaluation framework tests agent quality using Azure AI Foundry's built-in evaluators, with results viewable in the Foundry Portal.

### Running Evaluations

```bash
cd src

# Single-turn + multi-turn evaluations
python -m app.eval.multi_agent_eval --log-to-foundry

# Include agent-specific evaluators (tool usage quality)
python -m app.eval.multi_agent_eval --log-to-foundry --include-agent-evals

# Single-turn only
python -m app.eval.multi_agent_eval --log-to-foundry --single-turn-only

# Filter by category
python -m app.eval.multi_agent_eval --log-to-foundry --category licensing
```

### Evaluation Flow

```
1. Test data (test_data.json) → Agent queries → Responses collected
2. Responses + evaluator config → Foundry SDK → Cloud evaluation
3. Results → Foundry Portal (scores, trends, drill-down)
```

### Available Evaluators

**Quality Evaluators** — measure response quality for any LLM application:

| Evaluator | Purpose | When to Use |
|-----------|---------|-------------|
| `builtin.coherence` | Logical flow and consistency | Always — basic quality check |
| `builtin.fluency` | Grammar and readability | Always — ensures professional responses |
| `builtin.relevance` | Response addresses the query | Always — ensures on-topic answers |
| `builtin.groundedness` | Response supported by context | RAG/retrieval scenarios — prevents hallucination |

**Safety Evaluators** — catch harmful content:

| Evaluator | Purpose |
|-----------|---------|
| `builtin.violence` | Detects violent content |
| `builtin.sexual` | Detects sexual content |
| `builtin.self_harm` | Detects self-harm content |
| `builtin.hate_unfairness` | Detects hate speech and unfairness |

**Agent Evaluators** — measure tool-using behavior (use `--include-agent-evals`):

| Evaluator | Purpose |
|-----------|---------|
| `builtin.tool_call_accuracy` | Overall tool call quality — right tool, right params |
| `builtin.tool_call_success` | Tool calls completed without errors |
| `builtin.tool_input_accuracy` | Tool parameters are correct |
| `builtin.tool_output_utilization` | Agent correctly uses tool outputs |
| `builtin.tool_selection` | Agent picks appropriate tools |
| `builtin.task_completion` | Agent completes the entire task end-to-end |

> **Cost Note:** Agent evaluators analyze tool call traces and are more expensive. Use `--include-agent-evals` only when testing tool-using behavior.

### Viewing Results

| Data | Where | What You'll See |
|------|-------|-----------------|
| **Evaluations** | Foundry Portal → Your Project → Evaluations | Scores per evaluator, trends over time |
| **Logs** | Azure Portal → App Insights → Logs | KQL queries over `traces` table |
| **Traces** | Azure Portal → App Insights → Transaction Search | Waterfall view of request flow |
| **Errors** | Azure Portal → App Insights → Failures | Error rates, stack traces |

For a deep-dive on evaluation setup, test data format, and custom evaluators, see [EVALUATION_GUIDE.md](EVALUATION_GUIDE.md).

---

## Workbook Dashboard

The project includes a pre-built Azure Monitor Workbook ([`scripts/workbook-template.json`](../scripts/workbook-template.json)) with 7 monitoring tabs:

| Tab | What It Shows |
|-----|---------------|
| **Health Overview** | Request volume, avg/P95 latency, failure rate (KPI tiles + timechart) |
| **Agent Routing** | Agent invocation counts, routing chain patterns, handoff distribution |
| **Token Usage** | Input/output tokens by model over time, totals grid |
| **Tool Performance** | Avg/P95 tool execution duration, call counts |
| **Errors** | Error trend (logs + exceptions + failed calls), recent exceptions grid |
| **Conversation Drilldown** | Paste an `operation_Id` to see the full trace waterfall |
| **Slow Requests** | P50/P95 latency trends, top 20 slowest requests |

### Deploy the Workbook

```powershell
# From the repo root:
.\scripts\deploy-bot.ps1
Deploy-Workbook
```

The function auto-resolves the App Insights resource ID from your `.env` connection string. After deployment, open it in **Azure Portal → Application Insights → Workbooks → Cross-Tenant Bot Monitor**.

All queries use a parameterized time range picker (1h / 4h / 24h / 7d / 30d).

---

## KQL Queries & Dashboards

Use these queries in **Application Insights → Logs** to analyze bot behavior.

> **Quick reference:** See [KQL_CHEATSHEET.md](KQL_CHEATSHEET.md) for a copy-paste-ready set of queries covering traces, logs, metrics, and health dashboards.

### Common Queries

```kusto
-- Recent errors
traces
| where severityLevel >= 3
| order by timestamp desc
| take 100

-- Follow a specific conversation
traces
| where customDimensions.conversation_id == "CONVERSATION_ID"
| order by timestamp asc

-- Find slow LLM calls (> 5 seconds)
requests
| where duration > 5000
| order by duration desc

-- Count errors by type (last 24h)
traces
| where timestamp > ago(24h)
| where severityLevel >= 4
| summarize count() by tostring(customDimensions.error_type)

-- All requests from a specific user
traces
| where customDimensions.user_id == "USER_ID"
| order by timestamp desc
```

### Agent-Specific Queries

```kusto
-- Agent chat trace latency
dependencies
| where name == "Teams Bot Agent Chat"
| project timestamp, name, duration, success,
    customDimensions["agent.name"],
    customDimensions["conversation.id"]
| order by timestamp desc
| take 100

-- Agent latency over time (5min buckets)
dependencies
| where name == "Teams Bot Agent Chat"
| summarize avg(duration), percentile(duration, 95) by bin(timestamp, 5m)
| render timechart

-- End-to-end transaction view
traces
| union dependencies, requests
| where operation_Id == "YOUR-OPERATION-ID"
| project timestamp, itemType, name, duration, success
| order by timestamp asc

-- Bot logs by module
traces
| where customDimensions["LoggerName"] startswith "cross-tenant-bot"
| project timestamp, severityLevel, message,
    customDimensions["LoggerName"]
| order by timestamp desc
| take 100
```

### Severity Levels

| Level | Name | Description |
|-------|------|-------------|
| 0 | Verbose | Debug information |
| 1 | Information | Normal operations |
| 2 | Warning | Potential issues |
| 3 | Error | Handled errors |
| 4 | Critical | Failures |

---

## Alerts & Monitoring

### Setting Up Alerts

**Agent failure alert:**
1. Azure Portal → Application Insights → Alerts → Create alert rule
2. Condition: Custom log search
3. Query:
```kusto
dependencies
| where name == "Teams Bot Agent Chat"
| where success == false
| summarize count() by bin(timestamp, 5m)
```
4. Trigger: Greater than 5 failures in 5 minutes

**High latency alert:**
1. Condition: Metric → `dependencies/duration`
2. Filter: `dependency/name == "Teams Bot Agent Chat"`
3. Trigger: Average > 10,000ms

### Key Metrics to Monitor

| Metric | Description |
|--------|-------------|
| `requests/count` | Total incoming bot requests |
| `requests/duration` | Request latency (P50, P95, P99) |
| `dependencies/count` | Outbound calls (agent, Graph API) |
| `dependencies/duration` | Outbound call latency |
| `exceptions/count` | Exception rate |

### Useful Portal Blades

| What to See | Where to Go |
|-------------|-------------|
| Individual traces | Transaction Search |
| Agent call details | Logs → KQL for `dependencies` |
| Application logs | Logs → KQL for `traces` |
| Performance overview | Performance blade |
| Real-time data | Live Metrics |
| Service topology | Application Map |

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Azure Portal → App Insights → Overview → Connection String |
| `AZURE_AI_ENDPOINT` | Azure Portal → Azure OpenAI → Keys and Endpoint |
| `AZURE_AI_MODEL` | Azure OpenAI Studio → Deployments (e.g., `gpt-4o`) |
| `AZURE_AI_PROJECT_ENDPOINT` | Foundry Portal → Project → Settings → Endpoint |
| `LOCAL_TRACING` | Set to `true` to send traces to AI Toolkit (requires `LOCAL_DEBUG=true`) |

---

## Best Practices Checklist

### Setup
- [ ] Initialize Azure Monitor **BEFORE** logging configuration
- [ ] Set `APPLICATIONINSIGHTS_CONNECTION_STRING` in all environments
- [ ] Use `DefaultAzureCredential` for authentication

### Logging
- [ ] Use structured logging with `extra={}` for searchable context
- [ ] Never log PII, credentials, or full user queries
- [ ] Include correlation IDs (`conversation_id`, `request_id`) in all logs
- [ ] Reduce SDK noise: set Azure/OpenTelemetry loggers to WARNING

### Tracing
- [ ] Create meaningful span names (`agent_execution`, not `step1`)
- [ ] Add filterable attributes (`agent.id`, `conversation.id`, token counts)
- [ ] Nest spans to show request hierarchy

### Evaluations
- [ ] Run evaluations in CI/CD pipelines to catch regressions
- [ ] Use agent evaluators for tool-using agents
- [ ] Define quality thresholds and fail builds if not met
- [ ] Review Foundry Portal weekly for quality trends

### Production
- [ ] Set up alerts for error rate spikes
- [ ] Monitor LLM latency (P50, P95, P99)
- [ ] Track token usage for cost management
- [ ] Implement sampling for high-volume applications

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No data in App Insights | Verify `APPLICATIONINSIGHTS_CONNECTION_STRING` is set; data may take 2-5 minutes |
| Missing agent spans | Ensure `configure_telemetry()` is called at startup before any agent code |
| `NonRecordingSpan` errors | Remove `AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING` — it conflicts with Agent Framework instrumentation |
| Logs not appearing | Check logger name starts with `cross-tenant-bot` prefix |
| AI Toolkit not showing traces | Run `AI Toolkit: Open Trace` command first; verify port 4317 is available |

### Verify Data Flow

```kusto
union traces, dependencies, requests
| where timestamp > ago(30m)
| summarize count() by itemType
```

---

## References

- [Azure Monitor OpenTelemetry](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-enable)
- [Agent Framework Observability](https://github.com/microsoft/agent-framework)
- [Azure AI Evaluation SDK](https://learn.microsoft.com/en-us/azure/ai-studio/how-to/evaluate-sdk)
- [KQL Reference](https://learn.microsoft.com/en-us/kusto/query/)
- [EVALUATION_GUIDE.md](EVALUATION_GUIDE.md) — Detailed evaluation setup and custom evaluators
- [KQL_CHEATSHEET.md](KQL_CHEATSHEET.md) — Copy-paste KQL queries for App Insights
- [MULTI_AGENT_ORCHESTRATION.md](MULTI_AGENT_ORCHESTRATION.md) — Agent architecture details
