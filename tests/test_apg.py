"""
test_apg.py — Comprehensive APG Test Suite

Tests cover:
1. Pydantic schema validation (valid/invalid inputs)
2. Threshold extraction utility (plain + k-suffix amounts)
3. Deterministic guardrail node logic (no LLM required)
4. LangGraph graph structure and conditional edge routing
"""

from __future__ import annotations

from decimal import Decimal

import logfire
import pytest

from src.apg.schema import Policy, SpendIntent, ValidationResult
from src.apg.vector_db import extract_threshold_from_rule

# ---------------------------------------------------------------------------
# Configure logfire offline for all tests
# ---------------------------------------------------------------------------

logfire.configure(send_to_logfire=False)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pol_001() -> Policy:
    return Policy(
        id="POL-001",
        category="Hardware",
        rule="All laptop or desktop purchases exceeding $2,500 require VP-level approval.",
        exception_path="Route to Finance-VP-Queue",
    )


@pytest.fixture
def pol_002() -> Policy:
    return Policy(
        id="POL-002",
        category="Software/SaaS",
        rule="Any SaaS vendor handling PII or Customer Data must have a verified SOC2 Type II report on file.",
        exception_path="Trigger Security-Review-Workflow",
    )


@pytest.fixture
def pol_005() -> Policy:
    return Policy(
        id="POL-005",
        category="AI/Cloud",
        rule="GPU compute credits (AWS/GCP/Azure) exceeding $5k/month require CTO-Infrastructure approval.",
        exception_path="Route to Infra-Lead",
    )


# ---------------------------------------------------------------------------
# 1. Schema Validation Tests
# ---------------------------------------------------------------------------

class TestSpendIntent:
    def test_valid_intent(self):
        intent = SpendIntent(
            vendor="Apple",
            category="Hardware",
            amount=Decimal("100000.00"),
            justification="New engineering hires",
        )
        assert intent.vendor == "Apple"
        assert intent.amount == Decimal("100000.00")

    def test_string_amount_rejected(self):
        with pytest.raises(Exception):
            SpendIntent(
                vendor="Apple",
                category="Hardware",
                amount="one hundred thousand",
                justification="test",
            )

    def test_negative_amount_rejected(self):
        with pytest.raises(Exception):
            SpendIntent(
                vendor="Apple",
                category="Hardware",
                amount=Decimal("-100.00"),
                justification="test",
            )

    def test_zero_amount_rejected(self):
        with pytest.raises(Exception):
            SpendIntent(
                vendor="Apple",
                category="Hardware",
                amount=Decimal("0.00"),
                justification="test",
            )

    def test_invalid_category_rejected(self):
        with pytest.raises(Exception):
            SpendIntent(
                vendor="Apple",
                category="Entertainment",
                amount=Decimal("100.00"),
                justification="test",
            )

    def test_frozen_model_immutable(self):
        intent = SpendIntent(
            vendor="Apple", category="Hardware",
            amount=Decimal("100.00"), justification="test"
        )
        with pytest.raises(Exception):
            intent.vendor = "Samsung"

    def test_decimal_precision_preserved(self):
        """Ensure $2,500.01 is strictly greater than $2,500.00 (no float drift)."""
        a = Decimal("2500.01")
        b = Decimal("2500.00")
        assert a > b


# ---------------------------------------------------------------------------
# 2. Threshold Extraction Tests
# ---------------------------------------------------------------------------

class TestThresholdExtraction:
    def test_plain_dollar_amount(self):
        assert extract_threshold_from_rule(
            "All laptop purchases exceeding $2,500 require VP approval."
        ) == 2500

    def test_k_suffix_amount(self):
        assert extract_threshold_from_rule(
            "GPU credits exceeding $5k/month require CTO approval."
        ) == 5000

    def test_over_keyword(self):
        assert extract_threshold_from_rule(
            "Marketing expenses over $500 cannot use personal cards."
        ) == 500

    def test_10k_suffix(self):
        assert extract_threshold_from_rule(
            "New vendors must be vetted if contract value is >$10k."
        ) == 10000

    def test_no_threshold_returns_none(self):
        assert extract_threshold_from_rule("All purchases must have a PO.") is None


# ---------------------------------------------------------------------------
# 3. Guardrail Node Tests (deterministic — no LLM)
# ---------------------------------------------------------------------------

class TestValidateGuardrails:
    def _make_state(self, vendor, category, amount_str, policies):
        return {
            "request_text": "...",
            "extracted_intent": {
                "vendor": vendor,
                "category": category,
                "amount": amount_str,
                "justification": "test",
            },
            "retrieved_policies": [p.model_dump() for p in policies],
            "validation_result": None,
            "final_decision": "",
        }

    def test_hardware_over_limit_violated(self, pol_001):
        from src.apg.nodes import validate_guardrails
        state = self._make_state("Apple", "Hardware", "100000.00", [pol_001])
        result = validate_guardrails(state)["validation_result"]
        assert not result["is_compliant"]
        assert result["violated_policy_id"] == "POL-001"
        assert result["exception_workflow"] == "Route to Finance-VP-Queue"

    def test_hardware_under_limit_compliant(self, pol_001):
        from src.apg.nodes import validate_guardrails
        state = self._make_state("Apple", "Hardware", "2000.00", [pol_001])
        result = validate_guardrails(state)["validation_result"]
        assert result["is_compliant"]

    def test_hardware_at_exact_limit_compliant(self, pol_001):
        """$2,500.00 exactly is NOT 'exceeding' $2,500 — should be compliant."""
        from src.apg.nodes import validate_guardrails
        state = self._make_state("Apple", "Hardware", "2500.00", [pol_001])
        result = validate_guardrails(state)["validation_result"]
        assert result["is_compliant"]

    def test_saas_pii_triggers_soc2_check(self, pol_002):
        from src.apg.nodes import validate_guardrails
        state = self._make_state("Slack", "Software/SaaS", "500.00", [pol_002])
        result = validate_guardrails(state)["validation_result"]
        assert not result["is_compliant"]
        assert result["exception_workflow"] == "Trigger Security-Review-Workflow"

    def test_cloud_over_5k_violated(self, pol_005):
        from src.apg.nodes import validate_guardrails
        state = self._make_state("AWS", "AI/Cloud", "6000.00", [pol_005])
        result = validate_guardrails(state)["validation_result"]
        assert not result["is_compliant"]
        assert result["violated_policy_id"] == "POL-005"

    def test_no_policies_compliant(self):
        from src.apg.nodes import validate_guardrails
        state = self._make_state("Apple", "Hardware", "100000.00", [])
        result = validate_guardrails(state)["validation_result"]
        # No policies retrieved → no rules to violate → compliant
        assert result["is_compliant"]


# ---------------------------------------------------------------------------
# 4. Route Decision Tests
# ---------------------------------------------------------------------------

class TestRouteDecision:
    def test_compliant_result_approved(self):
        from src.apg.nodes import route_decision
        vr = ValidationResult(is_compliant=True, reason="All good.").model_dump()
        state = {"validation_result": vr}
        assert route_decision(state)["final_decision"] == "APPROVED"

    def test_non_compliant_generates_exception(self):
        from src.apg.nodes import route_decision
        vr = ValidationResult(
            is_compliant=False,
            reason="Over limit",
            violated_policy_id="POL-001",
            exception_workflow="Route to Finance-VP-Queue",
        ).model_dump()
        state = {"validation_result": vr}
        decision = route_decision(state)["final_decision"]
        assert "EXCEPTION" in decision
        assert "Finance-VP-Queue" in decision


# ---------------------------------------------------------------------------
# 5. Graph Structure Tests
# ---------------------------------------------------------------------------

class TestGraphStructure:
    def test_all_nodes_present(self):
        from src.apg.graph import app
        nodes = set(app.get_graph().nodes.keys())
        required = {
            "extract_intent", "retrieve_policies",
            "validate_guardrails", "route_decision", "route_to_dlq",
        }
        assert required.issubset(nodes)

    def test_conditional_edge_routes_dlq_on_none(self):
        from src.apg.graph import _check_extraction
        state = {
            "extracted_intent": None, "request_text": "gibberish",
            "retrieved_policies": [], "validation_result": None, "final_decision": "",
        }
        assert _check_extraction(state) == "dlq"

    def test_conditional_edge_routes_retrieve_on_success(self):
        from src.apg.graph import _check_extraction
        state = {
            "extracted_intent": {"vendor": "X", "category": "Hardware", "amount": "100", "justification": "y"},
            "request_text": "...",
            "retrieved_policies": [], "validation_result": None, "final_decision": "",
        }
        assert _check_extraction(state) == "retrieve"
