# Evaluation Guide

Comprehensive guide to the multi-agent evaluation framework for routing accuracy, handoff efficiency, context retention, and response quality.

---

## Table of Contents

1. [Overview](#overview)
2. [Running Evaluations](#running-evaluations)
3. [Test Data Format](#test-data-format)
4. [Custom Evaluators](#custom-evaluators)
5. [Foundry Built-in Evaluators](#foundry-built-in-evaluators)
6. [Results Format](#results-format)
7. [Adding Test Cases](#adding-test-cases)

---

## Overview

The evaluation framework (`src/app/eval/multi_agent_eval.py`) validates the multi-agent system across four dimensions:

| Dimension | What It Measures | Evaluator |
|-----------|-----------------|-----------|
| **Routing accuracy** | Does triage route to the correct specialist? | `RoutingAccuracyEvaluator` |
| **Handoff efficiency** | Clean handoff chains without loops or excessive hops? | `HandoffEfficiencyEvaluator` |
| **Context retention** | Is context preserved when agents switch mid-conversation? | `CrossAgentContextEvaluator` |
| **Response quality** | Coherence, fluency, relevance, task completion | Foundry built-in evaluators |

### Two Evaluation Modes

- **Single-turn** — Each test case is an independent query run through the full workflow
- **Multi-turn** — Sequences of turns forming conversations, testing routing across turns and context retention

### How It Works

The `MultiAgentEvalTarget` class runs each query through the real multi-agent workflow and introspects the result:
- Captures which agents were involved via workflow event scanning
- Records the handoff chain sequence
- Logs tool calls made by each agent
- Infers the final handling agent from events or response heuristics

---

## Running Evaluations

All commands run from the `src/` directory:

```bash
# Run all evaluations (single-turn + multi-turn)
python -m app.eval.multi_agent_eval

# Run multi-turn evaluations only
python -m app.eval.multi_agent_eval --multi-turn-only

# Log results to Azure AI Foundry Portal
python -m app.eval.multi_agent_eval --log-to-foundry
```

### Required Environment Variables

| Variable | Required For | Example |
|----------|-------------|---------|
| `AZURE_AI_ENDPOINT` | All modes | `https://myresource.openai.azure.com/` |
| `AZURE_AI_MODEL` | All modes | `gpt-4.1` |
| `LOCAL_DEBUG` | Local development | `true` |
| `AZURE_AI_PROJECT_ENDPOINT` | `--log-to-foundry` | `https://account.services.ai.azure.com/api/projects/proj` |
| `AZURE_AI_LICENSE_AGENT_ID` | License agent tests | `unified-knowledge-agent-1` |

### What `--log-to-foundry` Does

When enabled, evaluation results are uploaded to the Azure AI Foundry Portal using the Foundry SDK's evaluation API:
1. Converts results to JSONL format
2. Creates an evaluation object with Foundry built-in evaluators
3. Runs the evaluation in the cloud
4. Results appear in **Foundry Portal → Your Project → Evaluations**

---

## Test Data Format

Test data lives in `src/app/eval/test_data.json`.

### Single-Turn Structure

```json
{
  "single_turn": {
    "microsoft_in_scope": [
      {
        "query": "What is Azure Kubernetes Service?",
        "context": "",
        "ground_truth": "AKS is a managed Kubernetes container orchestration service",
        "category": "microsoft_in_scope",
        "expected_behavior": "should_answer",
        "expected_agent": "web_agent"
      }
    ],
    "licensing": [
      {
        "query": "What's included in Microsoft 365 E5?",
        "context": "",
        "ground_truth": "E5 includes advanced security, compliance, and analytics",
        "category": "licensing",
        "expected_behavior": "should_answer",
        "expected_agent": "license_agent"
      }
    ],
    "out_of_scope": [
      {
        "query": "What's the weather today?",
        "context": "",
        "ground_truth": "",
        "category": "out_of_scope",
        "expected_behavior": "should_decline",
        "expected_agent": "triage"
      }
    ],
    "greeting": [
      {
        "query": "Hello!",
        "context": "",
        "ground_truth": "",
        "category": "greeting",
        "expected_behavior": "should_greet",
        "expected_agent": "triage"
      }
    ]
  }
}
```

### Single-Turn Fields

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | The user's question |
| `context` | string | Optional context to include |
| `ground_truth` | string | Expected answer content (for quality evaluation) |
| `category` | string | Test category: `microsoft_in_scope`, `licensing`, `out_of_scope`, `greeting`, `acronym` |
| `expected_behavior` | string | `should_answer`, `should_decline`, `should_greet` |
| `expected_agent` | string | Agent that should handle this: `triage`, `web_agent`, `license_agent` |

### Multi-Turn Structure

```json
{
  "multi_turn": [
    {
      "id": "licensing_followup",
      "description": "Licensing question with follow-up about specific features",
      "category": "multi_turn",
      "turns": [
        {
          "query": "What license do I need for Microsoft Teams?",
          "expected_keywords": ["Teams", "license", "M365"],
          "expected_behavior": "should_answer",
          "expected_agent": "license_agent",
          "context_required": false
        },
        {
          "query": "Does that include phone system capabilities?",
          "expected_keywords": ["phone system", "calling"],
          "expected_behavior": "should_answer",
          "expected_agent": "license_agent",
          "context_required": true
        }
      ]
    }
  ]
}
```

### Multi-Turn Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique conversation identifier |
| `description` | string | What this conversation tests |
| `category` | string | Always `multi_turn` |
| `turns[].query` | string | User message for this turn |
| `turns[].expected_keywords` | string[] | Keywords expected in the response |
| `turns[].expected_behavior` | string | `should_answer`, `should_decline` |
| `turns[].expected_agent` | string | Agent that should handle this turn |
| `turns[].context_required` | bool | Whether this turn depends on prior context |

---

## Custom Evaluators

### RoutingAccuracyEvaluator

Compares `expected_agent` (from test data) with the actual agent that handled the query.

**Scoring**:
| Condition | Score |
|-----------|-------|
| Correct agent handled the query | 1.0 |
| Correct agent was involved but wasn't the final handler | 0.5 |
| Triage handled it when expected was `triage` but couldn't confirm | 0.8 |
| Wrong agent entirely | 0.0 |

**How the actual agent is determined**:
1. From workflow events: the last non-triage, non-coordinator agent in the handoff chain
2. If only triage/coordinator in events: returns `triage`
3. Fallback: response content heuristics (licensing keywords → `license_agent`, search/docs patterns → `web_agent`)

### HandoffEfficiencyEvaluator

Analyzes the handoff chain for loops and excessive hops.

**Scoring**:
| Condition | Score |
|-----------|-------|
| No handoff needed (direct response) | 1.0 |
| Efficient: ≤ 2 hops (triage → specialist) | 1.0 |
| Acceptable: 3 hops | 0.7 |
| Excessive: > 3 hops | 0.4 |
| Loop detected (A → B → A → B pattern) | 0.3 |

### CrossAgentContextEvaluator

Measures context retention when the conversation switches between agents across turns.

**Checks**:
- Whether expected keywords from the current turn appear in the response
- Whether the new agent explicitly references prior context ("as mentioned", "regarding", etc.)
- Term overlap between previous and current response

**Scoring**:
| Condition | Score |
|-----------|-------|
| No cross-agent context required | 1.0 |
| Same agent, keywords found | 1.0 |
| Agent switch, explicit references or ≥ 50% keywords | 1.0 |
| Agent switch, partial keywords or term overlap | 0.7 |
| Agent switch, context may be lost | 0.3 |

---

## Foundry Built-in Evaluators

When `--log-to-foundry` is used, these cloud-based evaluators are applied:

### Quality Evaluators

| Evaluator | Description |
|-----------|-------------|
| `builtin.coherence` | Logical flow and consistency of the response |
| `builtin.fluency` | Grammar, readability, and natural language quality |
| `builtin.relevance` | Whether the response addresses the query |

### Agent Evaluators

| Evaluator | Description |
|-----------|-------------|
| `builtin.intent_resolution` | Whether the agent correctly understood the user's intent |
| `builtin.task_adherence` | Whether the agent followed its instructions |
| `builtin.task_completion` | Whether the agent completed the task end-to-end |

### Tool Evaluators

| Evaluator | Description |
|-----------|-------------|
| `builtin.tool_call_accuracy` | Overall quality of tool calls |
| `builtin.tool_selection` | Whether the agent picked appropriate tools |
| `builtin.tool_call_success` | Whether tool calls completed without errors |

---

## Results Format

Results are saved as JSON to `src/app/eval/results/`.

### Filename Patterns

| Pattern | Content |
|---------|---------|
| `eval_YYYYMMDD_HHMMSS.json` | Single-turn evaluation results |
| `multi_turn_eval_YYYYMMDD_HHMMSS.json` | Multi-turn evaluation results |

### Single-Turn Result Shape

```json
{
  "timestamp": "2026-03-05T09:13:43",
  "results": [
    {
      "query": "What is AKS?",
      "response": "Azure Kubernetes Service (AKS) is...",
      "category": "microsoft_in_scope",
      "expected_agent": "web_agent",
      "actual_agent": "web_agent",
      "agents_involved": ["triage", "web_agent"],
      "handoff_chain": ["triage", "web_agent"],
      "tool_calls": [{"tool": "decode_microsoft_acronym", "event_type": "..."}],
      "routing_correct": true,
      "routing_score": 1.0,
      "routing_reason": "Correctly routed to web_agent",
      "handoff_score": 1.0,
      "handoff_hops": 2,
      "handoff_reason": "Efficient handoff: triage → web_agent"
    }
  ],
  "stats": {
    "total": 10,
    "routing_correct": 9,
    "routing_scores": [1.0, 1.0, 0.5, ...],
    "handoff_scores": [1.0, 1.0, 1.0, ...],
    "per_agent": {
      "web_agent": {"total": 5, "correct": 5},
      "license_agent": {"total": 3, "correct": 2},
      "triage": {"total": 2, "correct": 2}
    }
  }
}
```

### Multi-Turn Result Shape

```json
{
  "timestamp": "2026-03-05T12:32:14",
  "conversations": [
    {
      "conversation_id": "licensing_followup",
      "description": "Licensing question with follow-up",
      "category": "multi_turn",
      "total_turns": 2,
      "turns_passed": 2,
      "routing_accuracy": 1.0,
      "conversation_score": 0.95,
      "passed": true,
      "turns": [
        {
          "turn_number": 1,
          "query": "What license do I need for Teams?",
          "expected_agent": "license_agent",
          "actual_agent": "license_agent",
          "routing_correct": true,
          "keyword_score": 0.8,
          "context_score": 1.0,
          "turn_score": 0.9,
          "passed": true
        }
      ]
    }
  ]
}
```

---

## Adding Test Cases

### Adding a Single-Turn Test

1. Open `src/app/eval/test_data.json`
2. Add an entry to the appropriate category under `single_turn`:

```json
{
  "query": "What is the difference between Azure Functions and Logic Apps?",
  "context": "",
  "ground_truth": "Azure Functions is code-first serverless compute; Logic Apps is designer-first workflow automation",
  "category": "microsoft_in_scope",
  "expected_behavior": "should_answer",
  "expected_agent": "web_agent"
}
```

### Adding a Multi-Turn Conversation

1. Add a new object to the `multi_turn` array:

```json
{
  "id": "azure_to_licensing",
  "description": "Starts with Azure question, then switches to licensing",
  "category": "multi_turn",
  "turns": [
    {
      "query": "Tell me about Azure Virtual Desktop",
      "expected_keywords": ["AVD", "virtual desktop", "remote"],
      "expected_behavior": "should_answer",
      "expected_agent": "web_agent",
      "context_required": false
    },
    {
      "query": "What license do I need to use it?",
      "expected_keywords": ["license", "E3", "E5"],
      "expected_behavior": "should_answer",
      "expected_agent": "license_agent",
      "context_required": true
    }
  ]
}
```

### Guidelines for Good Test Cases

- **Cover all routing paths**: triage direct (greetings, refusals), web_agent, license_agent
- **Include edge cases**: ambiguous queries, mixed topics, follow-ups that switch agents
- **Set realistic `expected_keywords`**: 3-5 keywords that should appear in a good response
- **Use `context_required: true`** for turns that depend on prior conversation context
- **Balance categories**: ensure each agent has roughly equal test coverage
