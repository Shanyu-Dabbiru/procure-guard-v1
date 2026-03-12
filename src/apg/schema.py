"""
schema.py — APG Strict Data Models ("The Bouncer")

Defines all Pydantic V2 models used throughout the Autonomous Procurement
Guardrail. Using Decimal for all financial values to guarantee precision
suitable for SOC2-compliant financial auditing.
"""

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Spend Intent — produced by the LLM extraction node
# ---------------------------------------------------------------------------

SpendCategory = Literal[
    "Hardware",
    "Software/SaaS",
    "Vendor Management",
    "General Spend",
    "AI/Cloud",
    "Unknown",
]


class SpendIntent(BaseModel):
    """
    Structured representation of a procurement request extracted from
    natural language by the LLM. Every field is strictly typed so that
    downstream deterministic guardrails can operate on precise values.
    """

    vendor: str = Field(
        description="Legal name of the vendor being purchased from."
    )
    category: SpendCategory = Field(
        description=(
            "Procurement category that maps directly to a policy domain. "
            "Must be one of the defined literals."
        )
    )
    amount: Decimal = Field(
        gt=Decimal("0.00"),
        description=(
            "Total purchase amount in USD expressed as a Decimal to prevent "
            "floating-point rounding errors in financial comparisons."
        ),
    )
    justification: str = Field(
        description="Business justification provided by the requester."
    )

    model_config = {"frozen": True}  # Immutable after construction


# ---------------------------------------------------------------------------
# Policy — mirrors one entry from policies.json / Qdrant payload
# ---------------------------------------------------------------------------


class Policy(BaseModel):
    """
    A single corporate procurement policy rule retrieved from the
    Qdrant knowledge base.
    """

    id: str = Field(description="Unique policy identifier, e.g. 'POL-001'.")
    category: str = Field(
        description="Procurement category this policy governs."
    )
    rule: str = Field(description="Full human-readable text of the rule.")
    exception_path: str = Field(
        description=(
            "Workflow to trigger when this policy is violated, "
            "e.g. 'Route to Finance-VP-Queue'."
        )
    )

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Validation Result — produced by the deterministic guardrail node
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """
    The output of the 100 % deterministic guardrail validation node.
    No LLM is involved in producing this object — only strict Python
    logic so every decision is fully auditable.
    """

    is_compliant: bool = Field(
        description=(
            "True if the SpendIntent passes ALL retrieved policies. "
            "False if any single policy is violated."
        )
    )
    violated_policy_id: Optional[str] = Field(
        default=None,
        description="ID of the first policy violated, if any.",
    )
    reason: str = Field(
        description="Detailed, human-readable explanation for the verdict."
    )
    exception_workflow: Optional[str] = Field(
        default=None,
        description=(
            "The exception_path from the violated policy to trigger, "
            "e.g. 'Route to Finance-VP-Queue'. None when compliant."
        ),
    )
