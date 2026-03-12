"""
nodes.py — APG LangGraph Node Functions

Each function is a LangGraph node: it receives the full APGState and returns
a partial state dict with only updated keys. Nodes are designed to be:

  - extract_intent    : LLM-powered (only LLM call in the pipeline)
  - retrieve_policies : Qdrant hybrid search
  - validate_guardrails : 100 % deterministic Python — ZERO LLM involvement
  - route_decision    : Pure Python routing from ValidationResult
  - route_to_dlq      : Dead Letter Queue for unparseable requests
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import logfire
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.apg.schema import Policy, SpendIntent, ValidationResult
from src.apg.vector_db import extract_threshold_from_rule, retrieve_policies

# ---------------------------------------------------------------------------
# State type alias (defined in graph.py, imported here for type hints only)
# ---------------------------------------------------------------------------

APGStateDict = dict[str, Any]

# ---------------------------------------------------------------------------
# LLM — lazy singleton for the extraction node (avoids import-time API key check)
# ---------------------------------------------------------------------------

_llm: ChatOpenAI | None = None
_extract_chain = None

_EXTRACT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are a procurement analyst. Extract the structured spend "
                "intent from the user's request. Be precise with amounts — "
                "always express them as a plain decimal number in USD."
            ),
        ),
        ("human", "{request_text}"),
    ]
)


def _get_extract_chain():
    """Lazily build the extraction chain so tests can import without OPENAI_API_KEY."""
    global _llm, _extract_chain
    if _extract_chain is None:
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        _extract_chain = _EXTRACT_PROMPT | _llm.with_structured_output(SpendIntent)
    return _extract_chain


# ---------------------------------------------------------------------------
# Node 1: extract_intent
# ---------------------------------------------------------------------------


def extract_intent(state: APGStateDict) -> APGStateDict:
    """
    Parse the raw natural-language request into a strict SpendIntent.
    This is the ONLY node that calls an LLM.
    """
    with logfire.span("node.extract_intent"):
        request_text: str = state["request_text"]
        logfire.info("Extracting intent", request_text=request_text)

        try:
            intent: SpendIntent = _get_extract_chain().invoke(
                {"request_text": request_text}
            )
            logfire.info(
                "Intent extracted",
                vendor=intent.vendor,
                category=intent.category,
                amount=str(intent.amount),
            )
            return {"extracted_intent": intent.model_dump(mode="json")}
        except Exception as exc:
            logfire.error("Intent extraction failed", error=str(exc))
            # Signal failure with a sentinel so the conditional edge
            # can route this to the DLQ node.
            return {"extracted_intent": None}


# ---------------------------------------------------------------------------
# Node 2: retrieve_policies
# ---------------------------------------------------------------------------


def retrieve_policies_node(state: APGStateDict) -> APGStateDict:
    """
    Query Qdrant for policies relevant to the extracted intent using
    hybrid search (semantic + categorical hard filter).
    """
    with logfire.span("node.retrieve_policies"):
        raw_intent: dict = state["extracted_intent"]
        intent = SpendIntent(**{
            **raw_intent,
            "amount": Decimal(str(raw_intent["amount"])),
        })

        policies: list[Policy] = retrieve_policies(intent)
        logfire.info(
            "Policies retrieved",
            count=len(policies),
            ids=[p.id for p in policies],
        )
        return {"retrieved_policies": [p.model_dump() for p in policies]}


# ---------------------------------------------------------------------------
# Node 3: validate_guardrails  — 100 % DETERMINISTIC, NO LLM
# ---------------------------------------------------------------------------

# KEYWORDS that indicate a rule requires AMOUNT > threshold
_AMOUNT_KEYWORDS = re.compile(
    r"\b(exceeding|over|above|more than|greater than)\b", re.IGNORECASE
)


def validate_guardrails(state: APGStateDict) -> APGStateDict:
    """
    Apply corporate guardrails deterministically.

    Algorithm for each retrieved policy:
    1.  Parse the dollar threshold from the rule text.
    2.  If the rule contains an "exceeding / over / above" keyword AND the
        intent amount > threshold → policy violated.
    3.  SOC2 keyword check: if rule mentions SOC2 / PII and category is
        Software/SaaS → flag under the SOC2 path (human review required).

    Returns the first violation found. If none, intent is compliant.
    """
    with logfire.span("node.validate_guardrails"):
        raw_intent: dict = state["extracted_intent"]
        intent_amount = Decimal(str(raw_intent["amount"]))
        intent_category: str = raw_intent["category"]

        raw_policies: list[dict] = state.get("retrieved_policies", [])
        policies = [Policy(**p) for p in raw_policies]

        for policy in policies:
            rule_lower = policy.rule.lower()

            # --- Amount threshold check ---
            threshold = extract_threshold_from_rule(policy.rule)
            if threshold and _AMOUNT_KEYWORDS.search(policy.rule):
                if intent_amount > Decimal(str(threshold)):
                    result = ValidationResult(
                        is_compliant=False,
                        violated_policy_id=policy.id,
                        reason=(
                            f"Amount ${intent_amount} exceeds the "
                            f"${threshold:,} threshold defined in {policy.id}."
                        ),
                        exception_workflow=policy.exception_path,
                    )
                    logfire.warning(
                        "Policy violated (amount threshold)",
                        policy_id=policy.id,
                        amount=str(intent_amount),
                        threshold=threshold,
                    )
                    return {"validation_result": result.model_dump()}

            # --- SOC2 / PII keyword check (Software/SaaS category) ---
            if intent_category == "Software/SaaS" and any(
                kw in rule_lower for kw in ("soc2", "pii", "customer data")
            ):
                result = ValidationResult(
                    is_compliant=False,
                    violated_policy_id=policy.id,
                    reason=(
                        f"SaaS vendor requires SOC2 Type II verification "
                        f"per {policy.id}. Human security review triggered."
                    ),
                    exception_workflow=policy.exception_path,
                )
                logfire.warning(
                    "Policy violated (SOC2/PII)",
                    policy_id=policy.id,
                    vendor=raw_intent.get("vendor"),
                )
                return {"validation_result": result.model_dump()}

        # All policies passed
        result = ValidationResult(
            is_compliant=True,
            reason="Intent is compliant with all retrieved corporate policies.",
        )
        logfire.info("Intent is compliant")
        return {"validation_result": result.model_dump()}


# ---------------------------------------------------------------------------
# Node 4: route_decision
# ---------------------------------------------------------------------------


def route_decision(state: APGStateDict) -> APGStateDict:
    """
    Convert the ValidationResult into the human-readable final_decision string.
    """
    with logfire.span("node.route_decision"):
        raw_result: dict = state["validation_result"]
        result = ValidationResult(**raw_result)

        if result.is_compliant:
            decision = "APPROVED"
        else:
            decision = f"EXCEPTION: {result.exception_workflow}"

        logfire.info("Final decision", decision=decision)
        return {"final_decision": decision}


# ---------------------------------------------------------------------------
# DLQ Node — handles unparseable requests
# ---------------------------------------------------------------------------


def route_to_dlq(state: APGStateDict) -> APGStateDict:
    """
    Dead Letter Queue: called when intent extraction fails.
    Rejects the request and logs it for human review.
    """
    with logfire.span("node.route_to_dlq"):
        logfire.error(
            "Request routed to DLQ — intent could not be extracted",
            request_text=state.get("request_text"),
        )
        return {
            "final_decision": (
                "REJECTED (DLQ): Request could not be parsed into a valid "
                "spend intent. Routed for manual human review."
            )
        }
