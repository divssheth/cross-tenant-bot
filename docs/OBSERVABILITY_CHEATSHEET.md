# Azure AI Observability Cheat Sheet

Quick reference for logging, tracing, and evaluations in any Azure AI agent application.

---

## 1. Install Dependencies

```bash
pip install azure-monitor-opentelemetry opentelemetry-api azure-ai-projects azure-identity
```

| Package | Purpose |
|---------|---------|
| `azure-monitor-opentelemetry` | Sends logs/traces to Application Insights |
| `opentelemetry-api` | Standard tracing API |
| `azure-ai-projects` | Foundry SDK for evaluations |
| `azure-identity` | Azure authentication (managed identity, CLI, etc.) |

---

## 2. Telemetry Setup

**Why**: Azure Monitor OpenTelemetry automatically captures logs, traces, and metrics and sends them to Application Insights. This gives you a single place to debug issues across your entire application.

**How**: Call `configure_azure_monitor()` once at application startup. It hooks into Python's logging system and OpenTelemetry to automatically export telemetry.

```python
import os
from azure.monitor.opentelemetry import configure_azure_monitor

# Initialize ONCE at startup (BEFORE configuring logging)
# Why before logging? Because this call patches the logging system to forward logs to Azure Monitor.
# If you configure logging first, those handlers won't send to App Insights.
configure_azure_monitor(
    connection_string=os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"),
    logger_name="your-app-name",  # All loggers under this namespace will be captured
)
```

**Key Point**: Initialize this BEFORE any `logging.basicConfig()` or logger setup.

---

## 3. Structured Logging

**Why**: Structured logs with context (user_id, request_id, etc.) let you filter and search in Application Insights. Without context, you can't trace issues back to specific users or requests.

**How**: Use Python's `extra={}` parameter to add searchable fields. These become `customDimensions` in App Insights.

```python
import logging

# Get a logger under your app's namespace (matches logger_name from setup)
logger = logging.getLogger("your-app-name.module")

# ✅ Good: Structured with context
# The extra dict becomes searchable fields in App Insights
logger.info("Request processed", extra={
    "user_id": user_id,      # Filter by user
    "latency_ms": 150,       # Track performance
    "conversation_id": cid   # Correlate related logs
})

# ✅ Good: Errors with stack trace
# exc_info=True captures the full stack trace for debugging
logger.error("Processing failed", exc_info=True, extra={"request_id": req_id})

# ❌ Bad: Sensitive data in logs
# User queries may contain PII - truncate or hash if needed
logger.info(f"User query: {query}")  # May contain PII

# ❌ Bad: No context
# This tells you nothing about which request failed
logger.error("Error occurred")  # Unhelpful for debugging
```

**Pro Tip**: In App Insights, query with `traces | where customDimensions.user_id == "xxx"`

---

## 4. Distributed Tracing

**Why**: Traces show the full journey of a request across your application. For AI agents, this means seeing: request → LLM call → tool execution → response. You can measure latency at each step and identify bottlenecks.

**How**: Create "spans" that represent units of work. Spans can be nested (parent-child) to show the call hierarchy. Attributes on spans let you filter and search.

```python
from opentelemetry import trace

# Get a tracer - usually one per module
tracer = trace.get_tracer(__name__)

async def handle_chat_request(user_id: str, query: str):
    # Create a parent span for the entire request
    # This appears as a single "transaction" in App Insights
    with tracer.start_as_current_span("process_request") as span:
        # Attributes are searchable in App Insights Transaction Search
        span.set_attribute("user_id", user_id)
        span.set_attribute("request_type", "chat")
        
        # Nested span for LLM call - shows as child in the trace
        # You'll see exactly how long the LLM took vs other operations
        with tracer.start_as_current_span("llm_completion") as llm_span:
            llm_span.set_attribute("model", "gpt-4o")
            response = await call_llm(query)
            # Add after the call to capture actual values
            llm_span.set_attribute("tokens", response.usage.total_tokens)
        
        # Another nested span for tool execution
        # If tools are slow, you'll see it clearly in the trace
        with tracer.start_as_current_span("tool_execution") as tool_span:
            tool_span.set_attribute("tool_name", tool.name)
            result = await execute_tool(tool)
        
        return result
```

**Result in App Insights**: You see a waterfall view showing `process_request` containing `llm_completion` (1.2s) then `tool_execution` (0.3s).

---

## 5. Foundry Evaluations

**Why**: Evaluations systematically measure your agent's quality. Instead of manually checking responses, you run automated checks for coherence, safety, tool usage accuracy, etc. Results appear in Foundry Portal for tracking over time.

**How**: The Foundry SDK sends your test data to cloud evaluators. The evaluators (like `builtin.coherence`) run on Foundry's infrastructure, not locally. You define what data to evaluate and which evaluators to use.

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai.types.eval_create_params import DataSourceConfigCustom
from openai.types.evals.create_eval_jsonl_run_data_source_param import (
    CreateEvalJSONLRunDataSourceParam, SourceFileContent, SourceFileContentContent
)

# Step 1: Connect to your Foundry project
# DefaultAzureCredential works with: managed identity (prod), Azure CLI (dev), etc.
client = AIProjectClient(
    endpoint="https://<account>.services.ai.azure.com/api/projects/<project>",
    credential=DefaultAzureCredential()
).get_openai_client()  # Evaluations use the OpenAI-compatible API

# Step 2: Prepare your test data
# Each item is one test case with query + agent's response
# You typically generate responses by calling your agent locally first
eval_items = [
    SourceFileContentContent(item={
        "query": "What is Azure Functions?",
        "response": "Azure Functions is a serverless compute service..."
    })
    for item in test_data
]

# Step 3: Define the data schema
# This tells Foundry what fields your test data contains
data_config = DataSourceConfigCustom(
    type="custom",  # "custom" = you provide the data; "completions" = Foundry generates responses
    item_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "response": {"type": "string"},
        },
        "required": ["query", "response"],
    },
)

# Step 4: Define which evaluators to run
# Each evaluator scores your responses on a specific dimension
testing_criteria = [
    {
        "type": "azure_ai_evaluator",           # Use Foundry's built-in evaluators
        "name": "coherence",                     # Display name in results
        "evaluator_name": "builtin.coherence",   # The actual evaluator to use
        "initialization_parameters": {
            "deployment_name": "gpt-4o"          # LLM used by the evaluator
        },
        "data_mapping": {
            # Map your schema fields to evaluator inputs using Mustache syntax
            "query": "{{item.query}}",
            "response": "{{item.response}}",
        },
    },
]

# Step 5: Create the evaluation definition
eval_obj = client.evals.create(
    name="my-eval",
    data_source_config=data_config,
    testing_criteria=testing_criteria
)

# Step 6: Run the evaluation with your data
run = client.evals.runs.create(
    eval_id=eval_obj.id,
    name="run-1",
    data_source=CreateEvalJSONLRunDataSourceParam(
        type="jsonl",
        source=SourceFileContent(type="file_content", content=eval_items),
    ),
)

# Results appear in Foundry Portal → Evaluations after a few minutes
```

**Flow Summary**:
1. Your code generates agent responses locally
2. Foundry's cloud evaluators score those responses
3. Results appear in Foundry Portal for analysis

---

## 6. Available Evaluators

**Why different evaluators**: Different aspects of quality require different checks. Quality evaluators measure how well-written responses are. Safety evaluators catch harmful content. Agent evaluators are specifically designed for agents that use tools.

### Quality Evaluators
*Use these for any LLM application to measure response quality.*

| Name | Purpose | When to Use |
|------|---------|-------------|
| `builtin.coherence` | Logical flow and consistency | Always - basic quality check |
| `builtin.fluency` | Grammar and readability | Always - ensures professional responses |
| `builtin.relevance` | Response addresses the query | Always - ensures responses are on-topic |
| `builtin.groundedness` | Response supported by provided context | When using RAG/retrieval - prevents hallucination |

### Safety Evaluators
*Use these to ensure your agent doesn't generate harmful content.*

| Name | Purpose | When to Use |
|------|---------|-------------|
| `builtin.violence` | Detects violent content | Production apps - compliance requirement |
| `builtin.sexual` | Detects sexual content | Production apps - compliance requirement |
| `builtin.self_harm` | Detects self-harm content | Production apps - compliance requirement |
| `builtin.hate_unfairness` | Detects hate speech | Production apps - compliance requirement |

### Agent Evaluators
*Use these for agents that call tools/functions. They measure how well the agent uses its tools.*

| Name | Purpose | When to Use |
|------|---------|-------------|
| `builtin.tool_call_accuracy` | Overall tool call quality - right tool, right params | Agents with tools |
| `builtin.tool_call_success` | Tool calls completed without errors/timeouts | Agents with tools |
| `builtin.tool_input_accuracy` | Tool parameters are correct (types, values) | Agents with complex tool schemas |
| `builtin.tool_output_utilization` | Agent correctly uses tool outputs in response | Agents that synthesize tool results |
| `builtin.tool_selection` | Agent picks appropriate tools for the task | Agents with many available tools |
| `builtin.task_completion` | Agent completes the entire task end-to-end | Task-oriented agents |

**Cost Note**: Agent evaluators are more expensive as they analyze tool call traces. Use `--include-agent-evals` only when testing tool-using behavior.

---

## 7. Environment Variables

**Why these variables**: Each connects a different part of observability:
- **App Insights**: Where logs and traces are stored
- **Azure OpenAI**: The LLM your agent uses
- **Foundry Project**: Where evaluation results are stored and displayed

```bash
# Application Insights Connection String
# Where: Azure Portal → Application Insights → Overview → Connection String
# What it does: Tells your app where to send logs and traces
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=xxx;IngestionEndpoint=https://xxx.in.applicationinsights.azure.com/

# Azure OpenAI Endpoint
# Where: Azure Portal → Azure OpenAI → Keys and Endpoint
# What it does: Your agent's LLM endpoint
AZURE_AI_ENDPOINT=https://your-resource.openai.azure.com/

# Model Deployment Name
# Where: Azure OpenAI Studio → Deployments
# What it does: Which model deployment to use (also used by evaluators)
AZURE_AI_MODEL=gpt-4o

# Foundry Project Endpoint
# Where: Foundry Portal → Your Project → Settings → Endpoint
# What it does: Where evaluation results are stored and displayed
# Format: https://<account>.services.ai.azure.com/api/projects/<project>
AZURE_AI_PROJECT_ENDPOINT=https://<account>.services.ai.azure.com/api/projects/<project>
```

---

## 8. View Results

**Where to find your data**:

| Data | Location | What You'll See |
|------|----------|-----------------|
| **Logs** | Azure Portal → Application Insights → Logs | Query with KQL. Use `traces` table. Filter by `customDimensions` |
| **Traces** | Azure Portal → Application Insights → Transaction Search | Visual waterfall of request flow. Click any trace to see spans |
| **Errors** | Azure Portal → Application Insights → Failures | Aggregated error rates, stack traces, affected users |
| **Evaluations** | Foundry Portal → Your Project → Evaluations | Scores per evaluator, trends over time, drill into failures |

---

## 9. Quick KQL Queries (App Insights)

**Why KQL**: Application Insights uses Kusto Query Language (KQL) for searching logs. These queries help you find issues quickly.

```kusto
// Find recent errors (severityLevel: 1=Verbose, 2=Info, 3=Warning, 4=Error, 5=Critical)
traces
| where severityLevel >= 3
| order by timestamp desc
| take 100

// Follow a specific conversation across all logs
// Replace "xxx" with the conversation_id from your logs
traces
| where customDimensions.conversation_id == "xxx"
| order by timestamp asc

// Find slow LLM calls (duration > 5 seconds)
// Useful for identifying latency issues
requests
| where duration > 5000
| order by duration desc

// Count errors by type in the last 24 hours
// Good for spotting patterns
traces
| where timestamp > ago(24h)
| where severityLevel >= 4
| summarize count() by tostring(customDimensions.error_type)

// Find all requests from a specific user
traces
| where customDimensions.user_id == "user123"
| order by timestamp desc
```

---

## 10. Best Practices Checklist

### Setup
- [ ] Initialize Azure Monitor BEFORE logging configuration (or logs won't be captured)
- [ ] Set `APPLICATIONINSIGHTS_CONNECTION_STRING` in all environments
- [ ] Use `DefaultAzureCredential` for authentication (works everywhere)

### Logging
- [ ] Use structured logging with `extra={}` for searchable context
- [ ] Never log PII, credentials, or full user queries
- [ ] Include correlation IDs (conversation_id, request_id) in all logs
- [ ] Reduce SDK noise: set Azure/OpenTelemetry loggers to WARNING

### Tracing
- [ ] Create meaningful span names (`llm_completion`, not `step1`)
- [ ] Add attributes that help filtering (user_id, model, token_count)
- [ ] Nest spans to show the request hierarchy

### Evaluations
- [ ] Run evaluations in CI/CD pipelines (catch regressions early)
- [ ] Use agent evaluators (`--include-agent-evals`) for tool-using agents
- [ ] Define quality thresholds and fail builds if not met
- [ ] Review Foundry Portal weekly for quality trends

### Production
- [ ] Set up alerts for error rate spikes
- [ ] Monitor LLM latency (P50, P95, P99)
- [ ] Track token usage for cost management
- [ ] Implement sampling for high-volume applications

