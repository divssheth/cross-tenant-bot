# Telemetry Guide: Tracing, Monitoring & Logging

This guide explains how to view traces, logs, and metrics in Azure Application Insights for the Cross-Tenant Bot.

## Prerequisites

- Azure Application Insights resource
- `APPLICATIONINSIGHTS_CONNECTION_STRING` environment variable configured in ACA

## Architecture Overview

```
┌─────────────────┐   OpenTelemetry   ┌─────────────────────┐
│  Cross-Tenant   │ ───────────────▶  │  Azure Application  │
│     Bot         │   Traces/Logs     │      Insights       │
└─────────────────┘                   └─────────────────────┘
         │                                      │
         ▼                                      ▼
   ┌───────────┐                    ┌─────────────────────┐
   │  Foundry  │                    │  Log Analytics      │
   │   Agent   │                    │  Workspace (KQL)    │
   └───────────┘                    └─────────────────────┘
```

---

## 1. Viewing Traces

### Azure Portal Navigation

1. Go to **Azure Portal** → **Application Insights** → Your resource
2. Click **Transaction search** (left menu)
3. Or click **Performance** for aggregated trace data

### Finding Agent Traces

The bot creates these trace spans:

| Span Name | Description |
|-----------|-------------|
| `Teams Bot Agent Chat` | Main chat interaction with the agent |

### KQL Query for Agent Traces

In **Logs** section, run:

```kql
// All agent chat traces
dependencies
| where name == "Teams Bot Agent Chat"
| project timestamp, name, duration, success, 
    customDimensions["agent.name"],
    customDimensions["message.length"],
    customDimensions["response.length"],
    customDimensions["conversation.id"]
| order by timestamp desc
| take 100
```

### End-to-End Transaction View

```kql
// Get full trace with all spans
traces
| union dependencies, requests
| where operation_Id == "YOUR-OPERATION-ID"
| project timestamp, itemType, name, duration, success
| order by timestamp asc
```

---

## 2. Viewing Logs

### Azure Portal Navigation

1. Go to **Application Insights** → **Logs**
2. Use KQL queries below

### KQL Queries for Logs

#### All Bot Logs
```kql
traces
| where customDimensions["LoggerName"] startswith "cross-tenant-bot"
| project timestamp, severityLevel, message, 
    customDimensions["LoggerName"]
| order by timestamp desc
| take 100
```

#### Error Logs Only
```kql
traces
| where severityLevel >= 3  // Warning and above
| where customDimensions["LoggerName"] startswith "cross-tenant-bot"
| project timestamp, severityLevel, message
| order by timestamp desc
```

#### Agent-Specific Logs
```kql
traces
| where customDimensions["LoggerName"] contains "agents"
| project timestamp, severityLevel, message
| order by timestamp desc
| take 50
```

### Severity Levels

| Level | Name | Description |
|-------|------|-------------|
| 0 | Verbose | Debug information |
| 1 | Information | Normal operations |
| 2 | Warning | Potential issues |
| 3 | Error | Errors that were handled |
| 4 | Critical | Failures |

---

## 3. Viewing Metrics

### Azure Portal Navigation

1. Go to **Application Insights** → **Metrics**
2. Select namespace: **azure.applicationinsights** or **Custom Metrics**

### Key Metrics to Monitor

| Metric | Description |
|--------|-------------|
| `requests/count` | Total incoming requests |
| `requests/duration` | Request latency |
| `dependencies/count` | Outbound calls (Agent, Graph API) |
| `dependencies/duration` | Outbound call latency |
| `exceptions/count` | Exception rate |

### Custom KQL for Metrics

```kql
// Agent call latency over time
dependencies
| where name == "Teams Bot Agent Chat"
| summarize avg(duration), percentile(duration, 95) by bin(timestamp, 5m)
| render timechart
```

---

## 4. Setting Up Alerts

### Create Alert for Agent Failures

1. Go to **Application Insights** → **Alerts** → **Create alert rule**
2. Condition: Custom log search
3. Query:
```kql
dependencies
| where name == "Teams Bot Agent Chat"
| where success == false
| summarize count() by bin(timestamp, 5m)
```
4. Alert logic: Greater than 5 failures in 5 minutes

### Create Alert for High Latency

1. Condition: Metric
2. Signal: `dependencies/duration`
3. Filter: `dependency/name == "Teams Bot Agent Chat"`
4. Alert logic: Average > 10000ms

---

## 5. Application Map

### View Service Dependencies

1. Go to **Application Insights** → **Application map**
2. See visual representation of:
   - Cross-Tenant Bot
   - Azure AI Foundry (Agent calls)
   - Microsoft Graph API (RSC calls)

---

## 6. Live Metrics

### Real-Time Monitoring

1. Go to **Application Insights** → **Live Metrics**
2. See real-time:
   - Request rate
   - Request duration
   - Failure rate
   - Server health

---

## 7. Code Implementation Reference

### Trace Configuration ([trace_config.py](app/trace_config.py))

```python
from azure.monitor.opentelemetry import configure_azure_monitor

configure_azure_monitor(
    connection_string=os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"),
    logger_name="cross-tenant-bot",
)
```

### Creating Custom Spans ([foundry_agent_client.py](app/agents/foundry_agent_client.py))

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

@tracer.start_as_current_span("my_operation")
async def my_function():
    span = trace.get_current_span()
    span.set_attribute("custom.attribute", "value")
    # ... your code
```

### Logging ([log_config.py](app/log_config.py))

```python
import logging

logger = logging.getLogger("cross-tenant-bot")
logger.info("This will go to App Insights")
logger.error("Errors are tracked", exc_info=True)
```

---

## 8. Troubleshooting

### No Data in App Insights?

1. **Check connection string**: Verify `APPLICATIONINSIGHTS_CONNECTION_STRING` is set correctly in ACA
2. **Check ACA logs**: `az containerapp logs show --name crosstenant-bot-app -g tesco-bot-rg`
3. **Wait time**: Data may take 2-5 minutes to appear

### Query to Verify Data Flow

```kql
// Check if any data is coming in
union traces, dependencies, requests
| where timestamp > ago(30m)
| summarize count() by itemType
```

### Common Issues

| Issue | Solution |
|-------|----------|
| No traces | Check `APPLICATIONINSIGHTS_CONNECTION_STRING` value |
| Missing agent spans | Ensure `configure_azure_monitor_telemetry()` is called at startup |
| Logs not appearing | Check logger name matches `cross-tenant-bot` prefix |

---

## 9. Quick Reference Commands

### Check ACA Environment Variables
```powershell
az containerapp show --name crosstenant-bot-app -g tesco-bot-rg `
  --query "properties.template.containers[0].env[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING']"
```

### View ACA Container Logs
```powershell
az containerapp logs show --name crosstenant-bot-app -g tesco-bot-rg --follow
```

### Open App Insights in Portal
```powershell
az monitor app-insights component show -g tesco-bot-rg --query "[].id" -o tsv | `
  ForEach-Object { Start-Process "https://portal.azure.com/#resource$_" }
```

---

## 10. Dashboard Setup (Optional)

Create a custom Azure Dashboard with these tiles:

1. **Request Rate** - Line chart of `requests/count`
2. **Agent Latency** - Line chart of `dependencies/duration` filtered by `Teams Bot Agent Chat`
3. **Error Rate** - Number tile of `exceptions/count`
4. **Logs Stream** - Log query pinned from Logs blade

---

## Summary

| What to See | Where to Go |
|-------------|-------------|
| Individual traces | Transaction Search |
| Agent call details | Logs → KQL query for `dependencies` |
| Application logs | Logs → KQL query for `traces` |
| Performance overview | Performance blade |
| Real-time data | Live Metrics |
| Service topology | Application Map |
| Custom dashboards | Dashboards |
