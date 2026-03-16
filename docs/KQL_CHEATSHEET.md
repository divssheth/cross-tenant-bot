# KQL Cheatsheet – App Insights Queries

Quick-reference queries for the Cross-Tenant Multi-Agent Teams Bot.  
Run these in **Azure Portal → Application Insights → Logs**.

> **Tip:** Agent Framework spans land in `dependencies` (outgoing `CLIENT` calls).  
> Python logs land in `traces`. Data takes 2–5 min to appear.

---

## Traces

### Full agent waterfall (last hour)

```kql
dependencies
| where timestamp > ago(1h)
| where name has "invoke_agent" or name has "chat" or name has "execute_tool" or name has "Agent Chat"
| project timestamp, name, duration, success, operation_Id, operation_ParentId, customDimensions
| order by timestamp desc
```

### Agent routing summary

```kql
dependencies
| where timestamp > ago(1h)
| where name has "invoke_agent"
| extend agentName = tostring(customDimensions["gen_ai.agent.name"])
| summarize count(), avgDuration=avg(duration), failureCount=countif(success == false) by agentName
| order by count_ desc
```

### Drill into a single trace

```kql
union dependencies, requests, traces, exceptions
| where operation_Id == "<paste-trace-id-here>"
| order by timestamp asc
| project timestamp, itemType, name, message, duration, success, severityLevel
```

### Failed agent calls (last 24h)

```kql
dependencies
| where timestamp > ago(24h)
| where name has "invoke_agent" or name has "Agent Chat"
| where success == false
| project timestamp, name, duration, operation_Id, resultCode, customDimensions
| order by timestamp desc
```

---

## Logs

### All bot logs

```kql
traces
| where timestamp > ago(1h)
| where customDimensions["logger.name"] startswith "cross-tenant-bot"
| project timestamp, message, severityLevel, operation_Id, customDimensions["logger.name"]
| order by timestamp desc
```

### Errors only

```kql
traces
| where timestamp > ago(24h)
| where severityLevel >= 3
| where customDimensions["logger.name"] startswith "cross-tenant-bot"
| project timestamp, message, severityLevel, operation_Id
| order by timestamp desc
```

### Exceptions with stack traces

```kql
exceptions
| where timestamp > ago(24h)
| project timestamp, type, outerMessage, innermostMessage, details, operation_Id
| order by timestamp desc
```

---

## Metrics

### Token usage per model

```kql
customMetrics
| where timestamp > ago(1h)
| where name == "gen_ai.client.token.usage"
| extend model = tostring(customDimensions["gen_ai.request.model"]),
         tokenType = tostring(customDimensions["gen_ai.token.type"])
| summarize totalTokens=sum(value) by model, tokenType, bin(timestamp, 5m)
| render timechart
```

### LLM call duration

```kql
customMetrics
| where timestamp > ago(1h)
| where name == "gen_ai.client.operation.duration"
| extend model = tostring(customDimensions["gen_ai.request.model"])
| summarize avgDuration=avg(value), p95=percentile(value, 95), count() by model, bin(timestamp, 5m)
| render timechart
```

### Tool execution duration

```kql
customMetrics
| where timestamp > ago(1h)
| where name == "agent_framework.function.invocation.duration"
| extend functionName = tostring(customDimensions["gen_ai.tool.name"])
| summarize avgDuration=avg(value), p95=percentile(value, 95), count() by functionName
| order by count_ desc
```

---

## Health Dashboard

### Request volume, latency & failure rate (last 24h)

```kql
dependencies
| where timestamp > ago(24h)
| where name has "Agent Chat"
| summarize
    requests=count(),
    avgLatency=avg(duration),
    p95Latency=percentile(duration, 95),
    failRate=round(100.0 * countif(success == false) / count(), 2)
    by bin(timestamp, 1h)
| render timechart
```

### Slowest requests

```kql
dependencies
| where timestamp > ago(24h)
| where name has "Agent Chat"
| top 10 by duration desc
| project timestamp, name, duration, operation_Id, success
```
