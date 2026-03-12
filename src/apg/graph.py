"""
graph.py — APG LangGraph State Machine ("The Traffic Cop")

Compiles the APGState TypedDict and wires all nodes and edges into a
deterministic StateGraph. The compiled `app` object is the single entry
point for processing a procurement request end-to-end.

State transitions:
    START
      └──> extract_intent
              ├─── (success) ──> retrieve_policies
              │                        └──> validate_guardrails
              │                                   └──> route_decision
              │                                              └──> END
              └─── (failure) ──> route_to_dlq
                                       └──> END
"""

from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.apg.nodes import (
    extract_intent,
    retrieve_policies_node,
    route_decision,
    route_to_dlq,
    validate_guardrails,
)


# ---------------------------------------------------------------------------
# APG State Schema
# ---------------------------------------------------------------------------


class APGState(TypedDict):
    """
    Shared mutable state that flows through every node in the graph.

    Keys:
        request_text       : Raw natural-language procurement request.
        extracted_intent   : Dict of SpendIntent, or None on extraction failure.
        retrieved_policies : List of Policy dicts from Qdrant.
        validation_result  : Dict of ValidationResult from guardrail node.
        final_decision     : Human-readable verdict string.
    """

    request_text: str
    extracted_intent: Optional[dict[str, Any]]
    retrieved_policies: list[dict[str, Any]]
    validation_result: Optional[dict[str, Any]]
    final_decision: str


# ---------------------------------------------------------------------------
# Conditional edge — check extraction success
# ---------------------------------------------------------------------------


def _check_extraction(state: APGState) -> str:
    """
    Router function executed after `extract_intent`.

    Returns:
        "retrieve"  — intent extracted successfully, continue pipeline.
        "dlq"       — extraction failed, route to Dead Letter Queue.
    """
    if state.get("extracted_intent") is None:
        return "dlq"
    return "retrieve"


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

_builder = StateGraph(APGState)

# Register nodes
_builder.add_node("extract_intent", extract_intent)
_builder.add_node("retrieve_policies", retrieve_policies_node)
_builder.add_node("validate_guardrails", validate_guardrails)
_builder.add_node("route_decision", route_decision)
_builder.add_node("route_to_dlq", route_to_dlq)

# Edges
_builder.add_edge(START, "extract_intent")

_builder.add_conditional_edges(
    "extract_intent",
    _check_extraction,
    {
        "retrieve": "retrieve_policies",
        "dlq": "route_to_dlq",
    },
)

_builder.add_edge("retrieve_policies", "validate_guardrails")
_builder.add_edge("validate_guardrails", "route_decision")
_builder.add_edge("route_decision", END)
_builder.add_edge("route_to_dlq", END)

# Compile — exported as `app`, the public interface of the APG
app = _builder.compile()
