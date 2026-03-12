# Observability Guide

Comprehensive guide to tracing, logging, evaluations, and monitoring for the Cross-Tenant Multi-Agent Teams Bot.

## Table of Contents

- [Overview](#overview)
- [Quick Setup](#quick-setup)
- [Dual-Mode Tracing](#dual-mode-tracing)
- [Structured Logging](#structured-logging)
- [Distributed Tracing](#distributed-tracing)
- [Agent Evaluations](#agent-evaluations)
- [KQL Queries & Dashboards](#kql-queries--dashboards)
- [Alerts & Monitoring](#alerts--monitoring)
- [Environment Variables](#environment-variables)
- [Best Practices Checklist](#best-practices-checklist)

---

## Overview

The bot supports two telemetry modes that share the same OpenTelemetry foundation:

| Mode | When | How | View Results |
|------|------|-----|-------------|
| **AI Toolkit (Local)** | `LOCAL_DEBUG=true` | `configure_otel_providers(vs_code_extension_port=4317)` | VS Code AI Toolkit trace viewer |
| **Azure Monitor (Production)** | `APPLICATIONINSIGHTS_CONNECTION_STRING` set | `configure_azure_monitor(connection_string=...)` | Azure Portal → Application Insights |

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
| `opentelemetry-api` | Tracing spans and attributes |
| `agent-framework-azure-ai[observability]` | Agent Framework tracing for AI Toolkit |
| `azure-ai-evaluation` | Foundry evaluation SDK |

---

## Quick Setup

### Local Development (AI Toolkit)

1. Install the [AI Toolkit extension](https://marketplace.visualstudio.com/items?itemName=ms-windows-ai-studio.windows-ai-studio) in VS Code
2. Open the trace collector: **Cmd/Ctrl+Shift+P** → `AI Toolkit: Open Trace` (or `ai-mlstudio.tracing.open`)
3. Set `LOCAL_DEBUG=true` in your `.env`
4. Run the bot — traces appear in the AI Toolkit panel

### Production (Azure Monitor)

1. Create an Application Insights resource in Azure
2. Set `APPLICATIONINSIGHTS_CONNECTION_STRING` in your environment
3. Deploy — logs, traces, and metrics flow to App Insights automatically

---

## Dual-Mode Tracing

The [`trace_config.py`](../src/app/trace_config.py) module selects the telemetry provider automatically:

```python
from app.trace_config import configure_telemetry

# Called once at startup in __main__.py
# - LOCAL_DEBUG=true → Agent Framework tracing (AI Toolkit, port 4317)
# - Production → Azure Monitor (APPLICATIONINSIGHTS_CONNECTION_STRING)
configure_telemetry()
```

### How It Works

```python
def configure_telemetry() -> bool:
    local_debug = os.getenv("LOCAL_DEBUG", "").lower() in ("true", "1", "yes")
    if local_debug:
        if configure_agent_framework_tracing():
            return True
    return configure_azure_monitor_telemetry()
```

- **`configure_agent_framework_tracing()`** — Uses `agent_framework.observability.configure_otel_providers()` to export to the AI Toolkit OTLP collector on `localhost:4317`
- **`configure_azure_monitor_telemetry()`** — Uses `azure.monitor.opentelemetry.configure_azure_monitor()` to export to Application Insights

### Custom Span Attributes

The bot adds context to every trace span:

| Attribute | Source | Purpose |
|-----------|--------|---------|
| `agent.id` | Agent name | Identify which agent handled the request |
| `conversation.id` | Teams activity | Correlate spans within a conversation |
| `user.name` | Teams activity | Identify the requesting user |
| `user.message` | User input | Track what was asked |
| `response.length` | Agent output | Monitor response sizes |
| `handoff.from` / `handoff.to` | Orchestrator | Track agent-to-agent routing |

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

## KQL Queries & Dashboards

Use these queries in **Application Insights → Logs** to analyze bot behavior.

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
| `LOCAL_DEBUG` | Set to `true` for AI Toolkit tracing mode |

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
- [MULTI_AGENT_ORCHESTRATION.md](MULTI_AGENT_ORCHESTRATION.md) — Agent architecture details
