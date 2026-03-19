"""
Multi-Agent Evaluation Module

Evaluates the multi-agent orchestration system with routing introspection:
- Routing accuracy: Does triage route to the correct specialist?
- Handoff efficiency: Clean handoff chains without loops
- Cross-agent context: Context retention across agent switches
- Per-agent quality: Response quality grouped by handling agent

Run from project root:
  python -m app.eval.multi_agent_eval
  python -m app.eval.multi_agent_eval --multi-turn-only
  python -m app.eval.multi_agent_eval --log-to-foundry
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from dotenv import load_dotenv  # noqa: E402

# Ensure project root on path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

load_dotenv()

logger = logging.getLogger("cross-tenant-bot.eval.multi_agent")

AZURE_AI_MODEL = os.getenv("AZURE_AI_MODEL") or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4o")


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class AgentEvalResult:
    """Captures response + routing metadata from a workflow run."""
    response_text: str
    agents_involved: List[str] = field(default_factory=list)
    handoff_chain: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    total_events: int = 0
    inferred_agent: str = "unknown"
    error: Optional[str] = None


@dataclass
class TurnEvalResult:
    """Evaluation result for a single turn in a multi-agent conversation."""
    turn_number: int
    query: str
    response_preview: str
    expected_agent: str
    actual_agent: str
    routing_correct: bool
    keyword_score: float
    behavior_passed: bool
    context_score: float
    turn_score: float
    passed: bool
    agents_involved: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ConversationEvalResult:
    """Evaluation result for an entire multi-turn conversation."""
    conversation_id: str
    description: str
    category: str
    turns: List[TurnEvalResult] = field(default_factory=list)
    total_turns: int = 0
    turns_passed: int = 0
    routing_accuracy: float = 0.0
    conversation_score: float = 0.0
    passed: bool = False


# =============================================================================
# Multi-Agent Evaluation Target
# =============================================================================

class MultiAgentEvalTarget:
    """
    Evaluation target that runs the multi-agent workflow with routing introspection.

    Unlike the basic agent_target (which returns only response text),
    this target inspects workflow events to determine:
    - Which agents were involved in handling the query
    - What tools were called
    - The handoff chain sequence
    """

    def __init__(self):
        self._agents_created = False
        self._triage = None
        self._web_agent = None
        self._license_agent = None
        self._license_provider = None
        self._client = None

    async def initialize(self):
        """Initialize the multi-agent system (create agents once)."""
        if self._agents_created:
            return

        from agent_framework.azure import AzureOpenAIResponsesClient
        from azure.identity import AzureCliCredential, DefaultAzureCredential, ManagedIdentityCredential
        from app.agents.orchestrator import create_agents

        endpoint = os.getenv("AZURE_AI_ENDPOINT") or os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        model = os.getenv("AZURE_AI_MODEL") or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4o")

        local_tracing = os.getenv("LOCAL_TRACING", "").lower() in ("true", "1", "yes")
        local_debug = os.getenv("LOCAL_DEBUG", "").lower() in ("true", "1", "yes")
        client_id = os.getenv("AZURE_CLIENT_ID")

        if local_debug:
            credential = AzureCliCredential()
        elif client_id:
            credential = ManagedIdentityCredential(client_id=client_id)
        else:
            credential = DefaultAzureCredential()

        # Configure tracing for eval (optional — AI Toolkit local trace)
        if local_tracing:
            try:
                from agent_framework.observability import configure_otel_providers
                configure_otel_providers(
                    vs_code_extension_port=4317,
                    enable_sensitive_data=True,
                )
            except Exception:
                pass

        try:
            from opentelemetry.trace import NonRecordingSpan
            if not hasattr(NonRecordingSpan, "attributes"):
                NonRecordingSpan.attributes = property(lambda self: {})
            from azure.ai.projects.telemetry import AIProjectInstrumentor
            if not AIProjectInstrumentor().is_instrumented():
                AIProjectInstrumentor().instrument(enable_content_recording=local_tracing)
        except Exception:
            pass

        self._client = AzureOpenAIResponsesClient(
            credential=credential,
            endpoint=endpoint,
            deployment_name=model,
        )

        self._triage, self._web_agent, self._license_agent, self._license_provider = (
            await create_agents(self._client)
        )
        self._agents_created = True
        logger.info("Multi-agent eval target initialized")

    async def query(
        self,
        message: str,
        chat_history: Optional[list] = None,
    ) -> AgentEvalResult:
        """
        Run a query through the multi-agent workflow and capture routing metadata.

        Args:
            message: The user's message
            chat_history: Optional list of Message objects for multi-turn context

        Returns:
            AgentEvalResult with response text and routing metadata
        """
        await self.initialize()

        from agent_framework import Message, AgentResponseUpdate
        from app.agents.orchestrator import create_workflow

        # Build message list
        messages = []
        if chat_history:
            messages.extend(chat_history)
        messages.append(Message(role="user", text=message))

        # Create fresh workflow (same pattern as FoundryAgentClient)
        assert self._triage is not None and self._web_agent is not None and self._license_agent is not None
        workflow = create_workflow(self._triage, self._web_agent, self._license_agent)

        try:
            result = await workflow.run(messages)
        except Exception as e:
            return AgentEvalResult(
                response_text=f"ERROR: {e}",
                error=str(e),
            )

        # Extract response text from outputs
        response_text = ""
        outputs = result.get_outputs()
        for output in outputs:
            if isinstance(output, AgentResponseUpdate) and output.text:
                response_text += str(output.text)

        # Extract routing metadata from events
        agents_involved = []
        handoff_chain = []
        tool_calls_captured = []
        total_events = 0

        for event in result:
            total_events += 1
            data = getattr(event, "data", None)
            event_type = type(event).__name__

            # Fallback response extraction
            if not response_text and data is not None and hasattr(data, "text") and data.text:
                response_text = str(data.text)

            # Agent identification from event or event.data
            for src in (event, data):
                if src is None:
                    continue
                for attr in ("agent_name", "source", "agent", "name"):
                    val = getattr(src, attr, None)
                    if val and isinstance(val, str) and val != "ms-expert-orchestration":
                        if val not in agents_involved:
                            agents_involved.append(val)
                        handoff_chain.append(val)
                        break

            # Capture tool calls from events
            if data is not None:
                for attr in ("tool_calls", "calls"):
                    calls = getattr(data, attr, None)
                    if calls:
                        for tc in calls:
                            tool_name = getattr(tc, "name", None)
                            if not tool_name:
                                fn = getattr(tc, "function", None)
                                tool_name = getattr(fn, "name", "unknown") if fn else "unknown"
                            tool_calls_captured.append({
                                "tool": tool_name,
                                "event_type": event_type,
                            })

        if not response_text:
            response_text = "No response generated."

        # Infer which agent produced the final response
        inferred = self._infer_agent_from_response(
            response_text, message, agents_involved
        )

        return AgentEvalResult(
            response_text=response_text,
            agents_involved=agents_involved,
            handoff_chain=handoff_chain,
            tool_calls=tool_calls_captured,
            total_events=total_events,
            inferred_agent=inferred,
        )

    def _infer_agent_from_response(
        self, response_text: str, query: str, agents_from_events: List[str]
    ) -> str:
        """
        Infer which agent handled the query, using events first, then response heuristics.
        """
        # If events captured agent names, use them
        # The last specialist (non-triage, non-coordinator) in the chain is the handler
        specialist_agents = [
            a for a in agents_from_events
            if a not in ("triage", "handoff-coordinator", "ms-expert-orchestration")
        ]
        if specialist_agents:
            return specialist_agents[-1]

        # If triage is the only agent (direct response), return triage
        if agents_from_events and all(
            a in ("triage", "handoff-coordinator", "ms-expert-orchestration")
            for a in agents_from_events
        ):
            return "triage"

        # Fallback: heuristic from response content
        response_lower = response_text.lower()

        # Triage direct responses (greetings, declines)
        triage_indicators = [
            "microsoft expert assistant",
            "can only help with microsoft",
            "i'm unable to",
            "outside my scope",
        ]
        if any(ind in response_lower for ind in triage_indicators):
            return "triage"
        if len(response_text) < 200 and any(
            g in response_lower for g in ("hello", "hi!", "hey", "you're welcome")
        ):
            return "triage"

        # License agent responses
        license_keywords = [
            "license", "licensing", "subscription", "entitlement",
            "e3", "e5", "f1", "business premium", "knowledge base",
        ]
        license_score = sum(1 for kw in license_keywords if kw in response_lower)

        # Web agent responses
        web_keywords = [
            "search", "according to", "microsoft learn",
            "documentation", "https://", "learn.microsoft.com",
        ]
        web_score = sum(1 for kw in web_keywords if kw in response_lower)

        if license_score > web_score and license_score >= 2:
            return "license_agent"
        if web_score > 0 or len(response_text) > 300:
            return "web_agent"

        return "unknown"


# Global target instance (reused across evaluations)
_eval_target: Optional[MultiAgentEvalTarget] = None


def get_eval_target() -> MultiAgentEvalTarget:
    global _eval_target
    if _eval_target is None:
        _eval_target = MultiAgentEvalTarget()
    return _eval_target


def reset_eval_target():
    global _eval_target
    _eval_target = None


# =============================================================================
# Evaluators
# =============================================================================

class RoutingAccuracyEvaluator:
    """
    Evaluates if the triage agent routed to the correct specialist.

    Compares expected_agent (from test data) with the actual agent that
    handled the query (from workflow event introspection or heuristic inference).
    """

    def __call__(
        self,
        *,
        expected_agent: str,
        actual_agent: str,
        agents_involved: List[str],
    ) -> Dict[str, Any]:
        """
        Evaluate routing accuracy.

        Returns:
            dict with 'routing_correct' (bool), 'routing_score' (0-1), 'routing_reason' (str)
        """
        # Normalize names
        expected = expected_agent.lower().strip()
        actual = actual_agent.lower().strip()

        if expected == actual:
            return {
                "routing_correct": True,
                "routing_score": 1.0,
                "routing_reason": f"Correctly routed to {expected}",
            }

        # Partial credit: correct agent was involved but wasn't the final handler
        if expected in [a.lower() for a in agents_involved]:
            return {
                "routing_correct": False,
                "routing_score": 0.5,
                "routing_reason": f"Expected {expected}, got {actual} (but {expected} was involved)",
            }

        # Allow triage to handle things that were expected for web_agent in some cases
        # (triage might answer simple greetings or declines directly)
        if expected == "triage" and actual == "unknown":
            return {
                "routing_correct": True,
                "routing_score": 0.8,
                "routing_reason": "Likely triage direct response (could not confirm from events)",
            }

        return {
            "routing_correct": False,
            "routing_score": 0.0,
            "routing_reason": f"Expected {expected}, got {actual}",
        }


class HandoffEfficiencyEvaluator:
    """
    Evaluates handoff chain efficiency.

    Checks for:
    - Unnecessary loops (agent A → B → A → B)
    - Too many hops before reaching the specialist
    - Coordinator overhead
    """

    def __call__(
        self,
        *,
        handoff_chain: List[str],
        expected_agent: str,
    ) -> Dict[str, Any]:
        """
        Evaluate handoff efficiency.

        Returns:
            dict with 'handoff_score' (0-1), 'handoff_hops' (int), 'handoff_reason' (str)
        """
        if not handoff_chain:
            return {
                "handoff_score": 1.0,
                "handoff_hops": 0,
                "handoff_reason": "No handoff needed (direct response)",
            }

        # Filter out coordinator events (they're infrastructure, not agent hops)
        agent_hops = [
            a for a in handoff_chain
            if a not in ("handoff-coordinator", "ms-expert-orchestration")
        ]
        hop_count = len(agent_hops)

        # Check for loops: same agent appearing multiple non-consecutive times
        has_loop = False
        for i in range(len(agent_hops) - 2):
            if agent_hops[i] == agent_hops[i + 2] and agent_hops[i] != agent_hops[i + 1]:
                has_loop = True
                break

        if has_loop:
            return {
                "handoff_score": 0.3,
                "handoff_hops": hop_count,
                "handoff_reason": f"Loop detected in handoff chain: {' → '.join(agent_hops)}",
            }

        # Optimal: triage → specialist (2 hops) or direct triage (1 hop)
        if hop_count <= 2:
            return {
                "handoff_score": 1.0,
                "handoff_hops": hop_count,
                "handoff_reason": f"Efficient handoff: {' → '.join(agent_hops)}",
            }

        if hop_count <= 3:
            return {
                "handoff_score": 0.7,
                "handoff_hops": hop_count,
                "handoff_reason": f"Acceptable handoff: {' → '.join(agent_hops)}",
            }

        return {
            "handoff_score": 0.4,
            "handoff_hops": hop_count,
            "handoff_reason": f"Excessive hops ({hop_count}): {' → '.join(agent_hops)}",
        }


class CrossAgentContextEvaluator:
    """
    Evaluates context retention when the conversation switches between agents.

    Checks if context from a previous agent's response is preserved when
    a different agent handles the next turn.
    """

    def evaluate_turn(
        self,
        *,
        query: str,
        response: str,
        previous_agent: Optional[str],
        current_agent: str,
        previous_response: Optional[str],
        context_required: bool,
        expected_keywords: List[str],
    ) -> Dict[str, Any]:
        """
        Evaluate context retention for a single turn.

        Returns:
            dict with 'context_score' (0-1) and 'context_reason' (str)
        """
        if not context_required or previous_response is None:
            return {
                "context_score": 1.0,
                "context_reason": "No cross-agent context required",
            }

        response_lower = response.lower()
        prev_response_lower = previous_response.lower()

        agent_switched = previous_agent != current_agent

        # Check if expected keywords from this turn appear in the response
        keywords_found = sum(
            1 for kw in expected_keywords if kw.lower() in response_lower
        )
        keyword_ratio = keywords_found / len(expected_keywords) if expected_keywords else 1.0

        if not agent_switched:
            # Same agent — context should definitely be retained
            if keyword_ratio >= 0.3:
                return {
                    "context_score": 1.0,
                    "context_reason": "Same agent, context retained",
                }
            return {
                "context_score": 0.5,
                "context_reason": "Same agent but missing expected keywords",
            }

        # Agent switched — cross-agent context test
        # Check if the new agent's response acknowledges or builds on previous context
        context_indicators = [
            "as mentioned", "as discussed", "regarding", "about the",
            "you asked about", "earlier", "previously", "referring to",
        ]
        has_explicit_reference = any(
            ind in response_lower for ind in context_indicators
        )

        # Check if key terms from previous response appear in new response
        prev_terms = set(prev_response_lower.split())
        curr_terms = set(response_lower.split())
        # Only check substantive terms (> 4 chars)
        prev_substantive = {t for t in prev_terms if len(t) > 4}
        overlap = len(prev_substantive & curr_terms)
        term_overlap_ratio = overlap / len(prev_substantive) if prev_substantive else 0

        if has_explicit_reference or keyword_ratio >= 0.5:
            return {
                "context_score": 1.0,
                "context_reason": f"Agent switch ({previous_agent}→{current_agent}), context preserved",
            }
        if keyword_ratio >= 0.3 or term_overlap_ratio >= 0.1:
            return {
                "context_score": 0.7,
                "context_reason": f"Agent switch ({previous_agent}→{current_agent}), partial context",
            }
        return {
            "context_score": 0.3,
            "context_reason": f"Agent switch ({previous_agent}→{current_agent}), context may be lost",
        }


# =============================================================================
# Test Data
# =============================================================================

def load_test_data() -> dict:
    """Load test data from test_data.json."""
    json_path = Path(__file__).parent / "test_data.json"
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# Single-Turn Multi-Agent Evaluation
# =============================================================================

async def run_multi_agent_single_turn(test_data: Optional[list] = None):
    """
    Run single-turn evaluations with multi-agent routing introspection.

    Each test case is run through the full multi-agent workflow.
    Routing accuracy is evaluated by comparing expected_agent with the actual
    agent that handled the query.

    Returns:
        Tuple of (results, stats)
    """
    if test_data is None:
        data = load_test_data()
        # Flatten all single-turn categories
        st = data.get("single_turn", {})
        test_data = []
        for category_items in st.values():
            test_data.extend(category_items)

    target = get_eval_target()
    routing_eval = RoutingAccuracyEvaluator()
    handoff_eval = HandoffEfficiencyEvaluator()

    print("\n" + "=" * 70)
    print("🔀 Multi-Agent Single-Turn Evaluation (with routing introspection)")
    print("=" * 70)
    print(f"\nEvaluating {len(test_data)} test cases...")

    results = []
    stats = {
        "total": 0,
        "routing_correct": 0,
        "routing_scores": [],
        "handoff_scores": [],
        "per_agent": {},
    }

    for i, tc in enumerate(test_data):
        query = tc["query"]
        expected_agent = tc.get("expected_agent", "unknown")
        expected_behavior = tc.get("expected_behavior", "should_answer")
        category = tc.get("category", "unknown")

        print(f"\n[{i + 1}/{len(test_data)}] {category.upper()}")
        print(f"  Query: {query[:60]}...")
        print(f"  Expected agent: {expected_agent}")

        try:
            eval_result = await target.query(query)
            response = eval_result.response_text
            actual_agent = eval_result.inferred_agent
            print(f"  Actual agent: {actual_agent}")
            print(f"  Response: {response[:80]}...")
        except Exception as e:
            print(f"  ❌ Error: {e}")
            continue

        # Routing evaluation
        routing = routing_eval(
            expected_agent=expected_agent,
            actual_agent=actual_agent,
            agents_involved=eval_result.agents_involved,
        )

        # Handoff evaluation
        handoff = handoff_eval(
            handoff_chain=eval_result.handoff_chain,
            expected_agent=expected_agent,
        )

        status = "✅" if routing["routing_correct"] else "❌"
        print(f"  {status} Routing: {routing['routing_reason']}")
        print(f"  🔗 Handoff: {handoff['handoff_reason']}")

        if eval_result.tool_calls:
            tools = [tc["tool"] for tc in eval_result.tool_calls]
            print(f"  🔧 Tools: {', '.join(tools)}")

        result = {
            "query": query,
            "response": response,
            "category": category,
            "expected_agent": expected_agent,
            "actual_agent": actual_agent,
            "expected_behavior": expected_behavior,
            "agents_involved": eval_result.agents_involved,
            "handoff_chain": eval_result.handoff_chain,
            "tool_calls": eval_result.tool_calls,
            **routing,
            **handoff,
        }
        results.append(result)

        stats["total"] += 1
        if routing["routing_correct"]:
            stats["routing_correct"] += 1
        stats["routing_scores"].append(routing["routing_score"])
        stats["handoff_scores"].append(handoff["handoff_score"])

        # Per-agent tracking
        if actual_agent not in stats["per_agent"]:
            stats["per_agent"][actual_agent] = {"total": 0, "correct": 0}
        stats["per_agent"][actual_agent]["total"] += 1
        if routing["routing_correct"]:
            stats["per_agent"][actual_agent]["correct"] += 1

    return results, stats


# =============================================================================
# Multi-Turn Multi-Agent Evaluation
# =============================================================================

async def run_multi_agent_multi_turn(conversations: Optional[list] = None):
    """
    Run multi-turn evaluations with multi-agent routing introspection.

    Each conversation is a sequence of turns, potentially handled by
    different agents. Evaluates routing accuracy per turn, context retention
    across agent switches, and handoff efficiency.

    Returns:
        Tuple of (results, stats)
    """
    if conversations is None:
        data = load_test_data()
        conversations = data.get("multi_turn", [])

    target = get_eval_target()
    routing_eval = RoutingAccuracyEvaluator()
    context_eval = CrossAgentContextEvaluator()

    from agent_framework import Message

    print("\n" + "=" * 70)
    print("🔀🔄 Multi-Agent Multi-Turn Evaluation")
    print("=" * 70)
    print(f"\nEvaluating {len(conversations)} conversation flows...")

    conv_results: List[ConversationEvalResult] = []
    stats = {
        "total_conversations": 0,
        "conversations_passed": 0,
        "total_turns": 0,
        "turns_passed": 0,
        "routing_correct_turns": 0,
        "routing_scores": [],
        "context_scores": [],
        "cross_agent_switches": 0,
        "cross_agent_context_preserved": 0,
        "per_category": {},
    }

    for conv in conversations:
        conv_id = conv["id"]
        description = conv["description"]
        category = conv["category"]
        turns = conv["turns"]

        print(f"\n{'─' * 70}")
        print(f"📝 Conversation: {description}")
        print(f"   Category: {category} | Turns: {len(turns)}")
        print(f"{'─' * 70}")

        # Build chat history as we go
        chat_history: List[Message] = []
        turn_results: List[TurnEvalResult] = []
        prev_agent = None
        prev_response = None
        turns_passed = 0
        routing_correct_count = 0

        for i, turn in enumerate(turns):
            query = turn["query"]
            expected_keywords = turn.get("expected_keywords", [])
            expected_behavior = turn.get("expected_behavior", "should_answer")
            expected_agent = turn.get("expected_agent", "unknown")
            context_required = turn.get("context_required", False)

            print(f"\n  Turn {i + 1}/{len(turns)}: {query[:50]}...")
            print(f"    Expected agent: {expected_agent}")

            try:
                eval_result = await target.query(query, chat_history=chat_history)
                response = eval_result.response_text
                actual_agent = eval_result.inferred_agent
                print(f"    Actual agent: {actual_agent}")
                print(f"    Response: {response[:80]}...")
            except Exception as e:
                print(f"    ❌ Error: {e}")
                response = f"ERROR: {e}"
                actual_agent = "error"
                eval_result = AgentEvalResult(response_text=response, error=str(e))

            # Routing evaluation
            routing = routing_eval(
                expected_agent=expected_agent,
                actual_agent=actual_agent,
                agents_involved=eval_result.agents_involved,
            )

            # Context evaluation (cross-agent)
            context = context_eval.evaluate_turn(
                query=query,
                response=response,
                previous_agent=prev_agent,
                current_agent=actual_agent,
                previous_response=prev_response,
                context_required=context_required,
                expected_keywords=expected_keywords,
            )

            # Keyword matching
            response_lower = response.lower()
            keywords_found = sum(
                1 for kw in expected_keywords if kw.lower() in response_lower
            )
            keyword_score = keywords_found / len(expected_keywords) if expected_keywords else 1.0

            # Behavior compliance
            behavior_passed = _check_behavior(response, expected_behavior)

            # Composite turn score
            # Weights: routing 30%, keywords 25%, behavior 25%, context 20%
            turn_score = (
                routing["routing_score"] * 0.30
                + keyword_score * 0.25
                + (1.0 if behavior_passed else 0.0) * 0.25
                + context["context_score"] * 0.20
            )
            passed = turn_score >= 0.6

            # Print turn results
            r_status = "✅" if routing["routing_correct"] else "❌"
            ctx_icon = "📎" if context_required else "  "
            print(f"    {r_status} {ctx_icon} Score: {turn_score:.2f} | "
                  f"Routing: {routing['routing_score']:.1f} | "
                  f"Keywords: {keywords_found}/{len(expected_keywords)} | "
                  f"Context: {context['context_score']:.1f}")

            turn_eval = TurnEvalResult(
                turn_number=i + 1,
                query=query,
                response_preview=response[:200],
                expected_agent=expected_agent,
                actual_agent=actual_agent,
                routing_correct=routing["routing_correct"],
                keyword_score=keyword_score,
                behavior_passed=behavior_passed,
                context_score=context["context_score"],
                turn_score=turn_score,
                passed=passed,
                agents_involved=eval_result.agents_involved,
                tool_calls=eval_result.tool_calls,
            )
            turn_results.append(turn_eval)

            if passed:
                turns_passed += 1
            if routing["routing_correct"]:
                routing_correct_count += 1

            # Track cross-agent switches
            if prev_agent and actual_agent != prev_agent and context_required:
                stats["cross_agent_switches"] += 1
                if context["context_score"] >= 0.7:
                    stats["cross_agent_context_preserved"] += 1

            stats["routing_scores"].append(routing["routing_score"])
            stats["context_scores"].append(context["context_score"])

            # Update history for next turn
            chat_history.append(Message(role="user", text=query))
            chat_history.append(Message(role="assistant", text=response))
            prev_agent = actual_agent
            prev_response = response

        # Conversation-level results
        routing_accuracy = routing_correct_count / len(turns) if turns else 0
        conv_score = turns_passed / len(turns) if turns else 0
        conv_passed = conv_score >= 0.6 and routing_accuracy >= 0.5

        conv_result = ConversationEvalResult(
            conversation_id=conv_id,
            description=description,
            category=category,
            turns=turn_results,
            total_turns=len(turns),
            turns_passed=turns_passed,
            routing_accuracy=routing_accuracy,
            conversation_score=conv_score,
            passed=conv_passed,
        )
        conv_results.append(conv_result)

        status = "✅" if conv_passed else "❌"
        print(f"\n  {status} Conversation: {turns_passed}/{len(turns)} turns | "
              f"Routing: {routing_accuracy * 100:.0f}% | Score: {conv_score * 100:.0f}%")

        # Update stats
        stats["total_conversations"] += 1
        if conv_passed:
            stats["conversations_passed"] += 1
        stats["total_turns"] += len(turns)
        stats["turns_passed"] += turns_passed
        stats["routing_correct_turns"] += routing_correct_count

        if category not in stats["per_category"]:
            stats["per_category"][category] = {"total": 0, "passed": 0}
        stats["per_category"][category]["total"] += 1
        if conv_passed:
            stats["per_category"][category]["passed"] += 1

    return conv_results, stats


def _check_behavior(response: str, expected_behavior: str) -> bool:
    """Check if the response matches the expected behavior."""
    response_lower = response.lower()

    if expected_behavior == "should_answer":
        decline_phrases = [
            "can only help with microsoft", "unable to", "outside my scope",
        ]
        is_decline = any(p in response_lower for p in decline_phrases)
        return not is_decline and len(response) > 50

    if expected_behavior == "should_decline":
        decline_indicators = [
            "microsoft", "can only help", "unable", "scope",
        ]
        return any(ind in response_lower for ind in decline_indicators)

    if expected_behavior == "should_refuse":
        refuse_indicators = [
            "can't", "cannot", "won't", "refuse", "inappropriate",
            "harmful", "sorry",
        ]
        return any(ind in response_lower for ind in refuse_indicators)

    if expected_behavior == "should_clarify":
        clarify_indicators = [
            "which", "what", "specify", "clarify", "do you mean",
        ]
        return any(ind in response_lower for ind in clarify_indicators)

    return True  # may_vary


# =============================================================================
# Summary & Reporting
# =============================================================================

def print_single_turn_summary(results: list, stats: dict):
    """Print single-turn multi-agent evaluation summary."""
    print("\n" + "=" * 70)
    print("📋 MULTI-AGENT SINGLE-TURN SUMMARY")
    print("=" * 70)

    total = stats["total"]
    correct = stats["routing_correct"]
    pct = (correct / total * 100) if total > 0 else 0

    print(f"\n🎯 Routing Accuracy: {correct}/{total} ({pct:.0f}%)")

    avg_routing = _avg(stats["routing_scores"])
    avg_handoff = _avg(stats["handoff_scores"])
    print(f"📊 Avg Routing Score: {avg_routing:.2f}")
    print(f"🔗 Avg Handoff Score: {avg_handoff:.2f}")

    # Per-agent breakdown
    print("\n📊 Per-Agent Routing:")
    for agent, agent_stats in stats.get("per_agent", {}).items():
        a_pct = (agent_stats["correct"] / agent_stats["total"] * 100) if agent_stats["total"] > 0 else 0
        status = "✅" if a_pct >= 80 else "⚠️" if a_pct >= 50 else "❌"
        print(f"  {status} {agent:20} {agent_stats['correct']}/{agent_stats['total']} ({a_pct:.0f}%)")

    # Grade
    print("\n" + "=" * 70)
    if pct >= 80 and avg_handoff >= 0.7:
        print("🎉 SINGLE-TURN ROUTING GRADE: PASS")
    elif pct >= 50:
        print("⚠️  SINGLE-TURN ROUTING GRADE: NEEDS IMPROVEMENT")
    else:
        print("❌ SINGLE-TURN ROUTING GRADE: FAIL")
    print("=" * 70)


def print_multi_turn_summary(results: List[ConversationEvalResult], stats: dict):
    """Print multi-turn multi-agent evaluation summary."""
    print("\n" + "=" * 70)
    print("📋 MULTI-AGENT MULTI-TURN SUMMARY")
    print("=" * 70)

    total_c = stats["total_conversations"]
    passed_c = stats["conversations_passed"]
    c_pct = (passed_c / total_c * 100) if total_c > 0 else 0

    total_t = stats["total_turns"]
    passed_t = stats["turns_passed"]
    t_pct = (passed_t / total_t * 100) if total_t > 0 else 0

    routing_t = stats["routing_correct_turns"]
    r_pct = (routing_t / total_t * 100) if total_t > 0 else 0

    print(f"\n📝 Conversations: {passed_c}/{total_c} passed ({c_pct:.0f}%)")
    print(f"🔄 Turns: {passed_t}/{total_t} passed ({t_pct:.0f}%)")
    print(f"🎯 Routing Accuracy: {routing_t}/{total_t} correct ({r_pct:.0f}%)")

    avg_routing = _avg(stats["routing_scores"])
    avg_context = _avg(stats["context_scores"])
    print(f"📊 Avg Routing Score: {avg_routing:.2f}")
    print(f"🔗 Avg Context Score: {avg_context:.2f}")

    # Cross-agent context retention
    switches = stats["cross_agent_switches"]
    preserved = stats["cross_agent_context_preserved"]
    if switches > 0:
        s_pct = (preserved / switches * 100)
        print("\n🔀 Cross-Agent Context Retention:")
        print(f"   Agent switches requiring context: {switches}")
        print(f"   Context preserved: {preserved}/{switches} ({s_pct:.0f}%)")

    # Per-category breakdown
    print("\n📊 Results by Category:")
    for cat, cat_stats in stats.get("per_category", {}).items():
        cat_pct = (cat_stats["passed"] / cat_stats["total"] * 100) if cat_stats["total"] > 0 else 0
        status = "✅" if cat_pct >= 70 else "⚠️" if cat_pct >= 50 else "❌"
        print(f"  {status} {cat:35} {cat_stats['passed']}/{cat_stats['total']} ({cat_pct:.0f}%)")

    # Grade
    print("\n" + "=" * 70)
    if c_pct >= 70 and r_pct >= 70 and avg_context >= 0.6:
        print("🎉 MULTI-TURN MULTI-AGENT GRADE: PASS")
    elif c_pct >= 50 and r_pct >= 50:
        print("⚠️  MULTI-TURN MULTI-AGENT GRADE: NEEDS IMPROVEMENT")
    else:
        print("❌ MULTI-TURN MULTI-AGENT GRADE: FAIL")
    print("=" * 70)


def save_results(
    single_results: Optional[list] = None,
    single_stats: Optional[dict] = None,
    multi_results: Optional[list] = None,
    multi_stats: Optional[dict] = None,
):
    """Save evaluation results to JSON."""
    output_dir = Path(__file__).parent / "results"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"multi_agent_eval_{timestamp}.json"

    payload: Dict[str, Any] = {"timestamp": datetime.now().isoformat()}

    if single_results is not None:
        payload["single_turn"] = {
            "stats": {
                "total": single_stats["total"],
                "routing_correct": single_stats["routing_correct"],
                "avg_routing_score": _avg(single_stats["routing_scores"]),
                "avg_handoff_score": _avg(single_stats["handoff_scores"]),
                "per_agent": single_stats.get("per_agent", {}),
            },
            "results": single_results,
        }

    if multi_results is not None:
        payload["multi_turn"] = {
            "stats": {
                "total_conversations": multi_stats["total_conversations"],
                "conversations_passed": multi_stats["conversations_passed"],
                "total_turns": multi_stats["total_turns"],
                "turns_passed": multi_stats["turns_passed"],
                "routing_correct_turns": multi_stats["routing_correct_turns"],
                "avg_routing_score": _avg(multi_stats["routing_scores"]),
                "avg_context_score": _avg(multi_stats["context_scores"]),
                "cross_agent_switches": multi_stats["cross_agent_switches"],
                "cross_agent_context_preserved": multi_stats["cross_agent_context_preserved"],
                "per_category": multi_stats.get("per_category", {}),
            },
            "results": [
                {
                    "conversation_id": r.conversation_id,
                    "description": r.description,
                    "category": r.category,
                    "total_turns": r.total_turns,
                    "turns_passed": r.turns_passed,
                    "routing_accuracy": r.routing_accuracy,
                    "conversation_score": r.conversation_score,
                    "passed": r.passed,
                    "turns": [
                        {
                            "turn_number": t.turn_number,
                            "query": t.query,
                            "response_preview": t.response_preview,
                            "expected_agent": t.expected_agent,
                            "actual_agent": t.actual_agent,
                            "routing_correct": t.routing_correct,
                            "keyword_score": t.keyword_score,
                            "behavior_passed": t.behavior_passed,
                            "context_score": t.context_score,
                            "turn_score": t.turn_score,
                            "passed": t.passed,
                        }
                        for t in r.turns
                    ],
                }
                for r in multi_results
            ],
        }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\n📁 Results saved to: {output_file}")


# =============================================================================
# Foundry SDK Cloud Logging
# =============================================================================


def _build_agent_testing_criteria() -> list:
    """Build the full Foundry agent evaluator suite for multi-agent evaluation."""
    return [
        # General quality evaluators
        {
            "type": "azure_ai_evaluator",
            "name": "coherence",
            "evaluator_name": "builtin.coherence",
            "initialization_parameters": {"deployment_name": AZURE_AI_MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "fluency",
            "evaluator_name": "builtin.fluency",
            "initialization_parameters": {"deployment_name": AZURE_AI_MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "relevance",
            "evaluator_name": "builtin.relevance",
            "initialization_parameters": {"deployment_name": AZURE_AI_MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        # Agent-specific evaluators
        {
            "type": "azure_ai_evaluator",
            "name": "intent_resolution",
            "evaluator_name": "builtin.intent_resolution",
            "initialization_parameters": {"deployment_name": AZURE_AI_MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "task_adherence",
            "evaluator_name": "builtin.task_adherence",
            "initialization_parameters": {"deployment_name": AZURE_AI_MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "task_completion",
            "evaluator_name": "builtin.task_completion",
            "initialization_parameters": {"deployment_name": AZURE_AI_MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "tool_call_accuracy",
            "evaluator_name": "builtin.tool_call_accuracy",
            "initialization_parameters": {"deployment_name": AZURE_AI_MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "tool_selection",
            "evaluator_name": "builtin.tool_selection",
            "initialization_parameters": {"deployment_name": AZURE_AI_MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
        {
            "type": "azure_ai_evaluator",
            "name": "tool_call_success",
            "evaluator_name": "builtin.tool_call_success",
            "initialization_parameters": {"deployment_name": AZURE_AI_MODEL},
            "data_mapping": {
                "query": "{{item.query}}",
                "response": "{{item.response}}",
            },
        },
    ]


def run_multi_agent_eval_with_foundry(
    test_data: list,
    project_endpoint: str,
    evaluation_name: Optional[str] = None,
):
    """
    Run multi-agent evaluations and log to Foundry Portal.

    Flattens results into evaluation items with routing metadata
    for cloud-based analysis in the Foundry Portal.
    """
    import time
    from azure.identity import DefaultAzureCredential, AzureCliCredential

    try:
        from azure.ai.projects import AIProjectClient
        from openai.types.eval_create_params import DataSourceConfigCustom
        from openai.types.evals.create_eval_jsonl_run_data_source_param import (
            CreateEvalJSONLRunDataSourceParam,
            SourceFileContent,
            SourceFileContentContent,
        )
    except ImportError:
        print("❌ Error: azure-ai-projects package not installed.")
        print("   Install with: pip install --pre 'azure-ai-projects>=2.0.0b4'")
        return None

    if not evaluation_name:
        evaluation_name = f"multi-agent-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    print("\n📤 Running multi-agent evaluation with Foundry SDK...")
    print(f"   Project endpoint: {project_endpoint}")
    print(f"   Evaluation name: {evaluation_name}")

    try:
        try:
            credential = AzureCliCredential()
            project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)
        except Exception:
            credential = DefaultAzureCredential()
            project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)

        client = project_client.get_openai_client()
        print("   ✅ Connected to Foundry project")
    except Exception as e:
        print(f"❌ Error connecting to Foundry: {e}")
        return None

    # Get responses and routing metadata using a single event loop
    target = get_eval_target()

    async def _run_all_queries():
        results = []
        for i, tc in enumerate(test_data):
            print(f"   [{i + 1}/{len(test_data)}] {tc['query'][:50]}...")
            try:
                eval_result = await target.query(tc["query"])
            except Exception as e:
                eval_result = AgentEvalResult(response_text=f"ERROR: {e}", error=str(e))
            results.append((tc, eval_result))
        return results

    query_results = asyncio.run(_run_all_queries())
    eval_items = []

    for tc, eval_result in query_results:
        response = eval_result.response_text
        actual_agent = eval_result.inferred_agent if not eval_result.error else "error"

        # Compute actions from actual routing
        actual_actions = []
        chain = [a for a in eval_result.handoff_chain
                 if a not in ("handoff-coordinator", "ms-expert-orchestration")]
        if chain:
            for agent_name in chain:
                actual_actions.append(f"route_to_{agent_name}")
            actual_actions.append("generate_response")
        elif actual_agent not in ("unknown", "error"):
            actual_actions = [f"route_to_{actual_agent}", "generate_response"]
        else:
            actual_actions = ["generate_response"]

        # Compute expected actions from test data
        expected_agent_name = tc.get("expected_agent", "unknown")
        if expected_agent_name == "triage":
            expected_actions = ["generate_response"]
        else:
            expected_actions = [f"route_to_{expected_agent_name}", "generate_response"]

        eval_items.append(SourceFileContentContent(
            item={
                "query": tc["query"],
                "response": response,
                "ground_truth": tc.get("ground_truth", ""),
                "expected_agent": tc.get("expected_agent", "unknown"),
                "actual_agent": actual_agent,
                "routing_correct": str(
                    tc.get("expected_agent", "").lower() == actual_agent.lower()
                ),
            }
        ))

    print(f"   Prepared {len(eval_items)} items")

    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "response": {"type": "string"},
                "ground_truth": {"type": "string"},
                "expected_agent": {"type": "string"},
                "actual_agent": {"type": "string"},
                "routing_correct": {"type": "string"},
            },
            "required": ["query", "response"],
        },
    )

    testing_criteria = _build_agent_testing_criteria()

    print("\n   📊 Creating evaluation...")
    try:
        eval_object = client.evals.create(
            name=evaluation_name,
            data_source_config=data_source_config,
            testing_criteria=testing_criteria,  # type: ignore[arg-type]
        )
        print(f"   ✅ Evaluation created: {eval_object.id}")

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            eval_run = client.evals.runs.create(
                eval_id=eval_object.id,
                name=f"{evaluation_name}-run" if attempt == 1 else f"{evaluation_name}-run-retry{attempt}",
                data_source=CreateEvalJSONLRunDataSourceParam(
                    type="jsonl",
                    source=SourceFileContent(
                        type="file_content",
                        content=eval_items,
                    ),
                ),
            )
            print(f"   ✅ Run started: {eval_run.id}")

            print("   ⏳ Waiting for results...")
            while True:
                run = client.evals.runs.retrieve(run_id=eval_run.id, eval_id=eval_object.id)
                if run.status in ("completed", "failed", "cancelled"):
                    break
                time.sleep(5)
                print("      Still running...")

            if run.status == "completed":
                break

            if run.status == "failed" and attempt < max_attempts:
                print(f"   ⚠️ Evaluation run failed (attempt {attempt}/{max_attempts}), retrying in 10s...")
                time.sleep(10)
                continue

            print("   ❌ Evaluation failed after all retry attempts")
            return None

        output_items = list(
            client.evals.runs.output_items.list(run_id=run.id, eval_id=eval_object.id)
        )

        print(f"\n✅ Multi-agent evaluation complete! {len(output_items)} results")
        return {
            "eval_id": eval_object.id,
            "run_id": run.id,
            "status": run.status,
            "results": output_items,
        }

    except Exception as e:
        print(f"❌ Error running evaluation: {e}")
        import traceback
        traceback.print_exc()
        return None


def run_multi_turn_eval_with_foundry(
    conversations: list,
    project_endpoint: str,
    evaluation_name: Optional[str] = None,
):
    """
    Run multi-turn multi-agent evaluations and log to Foundry Portal.

    Flattens multi-turn conversations into per-turn evaluation items
    with accumulated conversation context and routing metadata.
    """
    import time
    from azure.identity import DefaultAzureCredential, AzureCliCredential

    try:
        from azure.ai.projects import AIProjectClient
        from openai.types.eval_create_params import DataSourceConfigCustom
        from openai.types.evals.create_eval_jsonl_run_data_source_param import (
            CreateEvalJSONLRunDataSourceParam,
            SourceFileContent,
            SourceFileContentContent,
        )
    except ImportError:
        print("❌ Error: azure-ai-projects package not installed.")
        print("   Install with: pip install --pre 'azure-ai-projects>=2.0.0b4'")
        return None

    if not evaluation_name:
        evaluation_name = f"multi-agent-multi-turn-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    print("\n📤 Running multi-turn multi-agent evaluation with Foundry SDK...")
    print(f"   Project endpoint: {project_endpoint}")
    print(f"   Evaluation name: {evaluation_name}")

    try:
        try:
            credential = AzureCliCredential()
            project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)
        except Exception:
            credential = DefaultAzureCredential()
            project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)

        client = project_client.get_openai_client()
        print("   ✅ Connected to Foundry project")
    except Exception as e:
        print(f"❌ Error connecting to Foundry: {e}")
        return None

    from agent_framework import Message

    target = get_eval_target()

    # Run all conversations in a single event loop to avoid MCP client conflicts
    async def _run_all_conversations():
        all_results = []  # list of (conv, turn_results)
        for conv in conversations:
            conv_id = conv["id"]
            description = conv["description"]
            turns = conv["turns"]

            print(f"\n   Processing conversation: {description}")

            chat_history: list = []
            turn_results = []

            for i, turn in enumerate(turns):
                query = turn["query"]
                print(f"      Turn {i + 1}/{len(turns)}: {query[:40]}...")

                try:
                    eval_result = await target.query(query, chat_history=chat_history)
                except Exception as e:
                    eval_result = AgentEvalResult(response_text=f"ERROR: {e}", error=str(e))

                response = eval_result.response_text
                # Update history for next turn
                chat_history.append(Message(role="user", text=query))
                chat_history.append(Message(role="assistant", text=response))

                turn_results.append((turn, eval_result))

            all_results.append((conv, turn_results))
        return all_results

    all_conv_results = asyncio.run(_run_all_conversations())
    eval_items = []

    for conv, turn_results in all_conv_results:
        conv_id = conv["id"]
        conversation_context_parts: list = []

        for i, (turn, eval_result) in enumerate(turn_results):
            query = turn["query"]
            expected_agent = turn.get("expected_agent", "unknown")
            response = eval_result.response_text
            actual_agent = eval_result.inferred_agent if not eval_result.error else "error"

            # Compute actions from actual routing
            actual_actions = []
            chain = [a for a in eval_result.handoff_chain
                     if a not in ("handoff-coordinator", "ms-expert-orchestration")]
            if chain:
                for agent_name in chain:
                    actual_actions.append(f"route_to_{agent_name}")
                actual_actions.append("generate_response")
            elif actual_agent not in ("unknown", "error"):
                actual_actions = [f"route_to_{actual_agent}", "generate_response"]
            else:
                actual_actions = ["generate_response"]

            # Compute expected actions
            if expected_agent == "triage":
                expected_actions = ["generate_response"]
            else:
                expected_actions = [f"route_to_{expected_agent}", "generate_response"]

            # Build context string from previous turns
            context_str = "\n".join(conversation_context_parts)[:2000] if conversation_context_parts else ""

            eval_items.append(SourceFileContentContent(
                item={
                    "query": query,
                    "response": response,
                    "ground_truth": ", ".join(turn.get("expected_keywords", [])),
                    "expected_agent": expected_agent,
                    "actual_agent": actual_agent,
                    "routing_correct": str(expected_agent.lower() == actual_agent.lower()),
                    "conversation_id": conv_id,
                    "turn_number": i + 1,
                    "conversation_context": context_str,
                }
            ))

            # Track context for Foundry evaluation items
            conversation_context_parts.append(f"User: {query}\nAssistant: {response}")

    print(f"\n   Prepared {len(eval_items)} evaluation items from {len(conversations)} conversations")

    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "response": {"type": "string"},
                "ground_truth": {"type": "string"},
                "expected_agent": {"type": "string"},
                "actual_agent": {"type": "string"},
                "routing_correct": {"type": "string"},
                "conversation_id": {"type": "string"},
                "turn_number": {"type": "integer"},
                "conversation_context": {"type": "string"},
            },
            "required": ["query", "response"],
        },
    )

    testing_criteria = _build_agent_testing_criteria()

    print("\n   📊 Creating multi-turn evaluation...")
    try:
        eval_object = client.evals.create(
            name=evaluation_name,
            data_source_config=data_source_config,
            testing_criteria=testing_criteria,  # type: ignore[arg-type]
        )
        print(f"   ✅ Evaluation created: {eval_object.id}")

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            eval_run = client.evals.runs.create(
                eval_id=eval_object.id,
                name=f"{evaluation_name}-run" if attempt == 1 else f"{evaluation_name}-run-retry{attempt}",
                data_source=CreateEvalJSONLRunDataSourceParam(
                    type="jsonl",
                    source=SourceFileContent(
                        type="file_content",
                        content=eval_items,
                    ),
                ),
            )
            print(f"   ✅ Run started: {eval_run.id}")

            print("   ⏳ Waiting for results...")
            while True:
                run = client.evals.runs.retrieve(run_id=eval_run.id, eval_id=eval_object.id)
                if run.status in ("completed", "failed", "cancelled"):
                    break
                time.sleep(5)
                print("      Still running...")

            if run.status == "completed":
                break

            if run.status == "failed" and attempt < max_attempts:
                print(f"   ⚠️ Evaluation run failed (attempt {attempt}/{max_attempts}), retrying in 10s...")
                time.sleep(10)
                continue

            print("   ❌ Evaluation failed after all retry attempts")
            return None

        output_items = list(
            client.evals.runs.output_items.list(run_id=run.id, eval_id=eval_object.id)
        )

        print(f"\n✅ Multi-turn multi-agent evaluation complete! {len(output_items)} results")
        return {
            "eval_id": eval_object.id,
            "run_id": run.id,
            "status": run.status,
            "results": output_items,
        }

    except Exception as e:
        print(f"❌ Error running multi-turn evaluation: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# Utilities
# =============================================================================

def _avg(vals: list) -> float:
    return sum(vals) / len(vals) if vals else 0.0


# =============================================================================
# CLI
# =============================================================================

def main():
    """Run multi-agent evaluation."""
    import argparse

    parser = argparse.ArgumentParser(description="Multi-Agent Evaluation")
    parser.add_argument(
        "--single-turn-only", action="store_true",
        help="Run only single-turn evaluations",
    )
    parser.add_argument(
        "--multi-turn-only", action="store_true",
        help="Run only multi-turn evaluations",
    )
    parser.add_argument(
        "--log-to-foundry", action="store_true",
        help="Log results to Foundry Portal",
    )
    parser.add_argument(
        "--evaluation-name", type=str, default=None,
        help="Name for evaluation run in Foundry Portal",
    )
    parser.add_argument(
        "--test-data", type=str, default=None,
        help="Path to custom test data JSON file",
    )
    args = parser.parse_args()

    print("\n🔀 Multi-Agent Orchestration Evaluation")
    print("=" * 70)

    endpoint = os.getenv("AZURE_AI_ENDPOINT") or os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        print("❌ Error: AZURE_AI_ENDPOINT / FOUNDRY_PROJECT_ENDPOINT not set")
        return

    print(f"Endpoint: {endpoint}")
    print(f"Model: {AZURE_AI_MODEL}")

    # Load test data
    if args.test_data:
        json_path = Path(args.test_data)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = load_test_data()

    run_single = not args.multi_turn_only
    run_multi = not args.single_turn_only

    single_results = None
    single_stats = None
    multi_results = None
    multi_stats = None

    if run_single:
        st = data.get("single_turn", {})
        test_cases = []
        for items in st.values():
            test_cases.extend(items)

        print(f"\nRunning {len(test_cases)} single-turn test cases...")

        if args.log_to_foundry:
            project_ep = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
            if not project_ep:
                print("❌ --log-to-foundry requires AZURE_AI_PROJECT_ENDPOINT")
                return
            run_multi_agent_eval_with_foundry(
                test_cases, project_ep, args.evaluation_name,
            )
        else:
            single_results, single_stats = asyncio.run(
                run_multi_agent_single_turn(test_cases)
            )
            print_single_turn_summary(single_results, single_stats)

    if run_multi:
        # Reset eval target to release stale async connections from single-turn run
        reset_eval_target()
        conversations = data.get("multi_turn", [])
        print(f"\nRunning {len(conversations)} multi-turn conversations...")

        if args.log_to_foundry:
            project_ep = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
            if not project_ep:
                print("❌ --log-to-foundry requires AZURE_AI_PROJECT_ENDPOINT")
                return
            run_multi_turn_eval_with_foundry(
                conversations, project_ep, args.evaluation_name,
            )
        else:
            multi_results, multi_stats = asyncio.run(
                run_multi_agent_multi_turn(conversations)
            )
            print_multi_turn_summary(multi_results, multi_stats)

    # Save results
    save_results(single_results, single_stats, multi_results, multi_stats)


if __name__ == "__main__":
    main()
