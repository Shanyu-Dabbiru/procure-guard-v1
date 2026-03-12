"""
main.py — APG Entry Point & Observability Setup

Initialises Pydantic Logfire for CFO-level audit tracing and wires the
LangGraph `app` to a simple async runner. Every request produces a single
unified Logfire trace spanning all 4 pipeline stages.

Usage:
    python -m src.apg.main "Buy 50 MacBooks from Apple for $100,000"
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import logfire

# ---------------------------------------------------------------------------
# Logfire — must be configured BEFORE any nodes are imported so all
# LangChain / Pydantic instrumentation is captured from the start.
# ---------------------------------------------------------------------------
import os

_send_to_logfire = os.getenv("LOGFIRE_TOKEN") is not None

logfire.configure(
    service_name="apg-guardrail",
    send_to_logfire=_send_to_logfire,
)
# Record all Pydantic model validations for SOC2-level audit tracing
logfire.instrument_pydantic(record="all")

# ---------------------------------------------------------------------------
# Post-Logfire imports (so tracing captures initialisation)
# ---------------------------------------------------------------------------
from src.apg.graph import app  # noqa: E402
from src.apg.vector_db import ingest_policies  # noqa: E402

# Path to the policies knowledge base
_POLICIES_PATH = Path(__file__).parent.parent.parent / "policies.json"


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


async def run_guardrail(request_text: str) -> dict:
    """
    Run a natural-language procurement request through the full APG pipeline.

    Returns the final state dict containing `final_decision` and all
    intermediate keys for audit purposes.
    """
    with logfire.span("apg.guardrail", request=request_text):
        logfire.info("APG pipeline started", request=request_text)

        initial_state = {
            "request_text": request_text,
            "extracted_intent": None,
            "retrieved_policies": [],
            "validation_result": None,
            "final_decision": "",
        }

        final_state = await app.ainvoke(initial_state)

        logfire.info(
            "APG pipeline complete",
            final_decision=final_state.get("final_decision"),
        )

    return final_state


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _print_result(state: dict) -> None:
    """Pretty-print the pipeline result to stdout."""
    print("\n" + "=" * 60)
    print("  AUTONOMOUS PROCUREMENT GUARDRAIL — RESULT")
    print("=" * 60)

    intent = state.get("extracted_intent") or {}
    if intent:
        print(f"\n📦  Vendor    : {intent.get('vendor')}")
        print(f"📂  Category  : {intent.get('category')}")
        print(f"💰  Amount    : ${intent.get('amount')}")
        print(f"📝  Reason    : {intent.get('justification')}")

    policies = state.get("retrieved_policies") or []
    if policies:
        print(f"\n📋  Matched policies : {[p['id'] for p in policies]}")

    vr = state.get("validation_result") or {}
    if vr:
        compliant = vr.get("is_compliant")
        icon = "✅" if compliant else "🚨"
        print(f"\n{icon}  Compliance  : {'PASS' if compliant else 'FAIL'}")
        print(f"   Reason      : {vr.get('reason')}")
        if vr.get("violated_policy_id"):
            print(f"   Violated    : {vr.get('violated_policy_id')}")

    print(f"\n⚖️   DECISION    : {state.get('final_decision')}")
    print("=" * 60 + "\n")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m src.apg.main '<procurement request>'")
        sys.exit(1)

    request_text = " ".join(sys.argv[1:])

    # Ingest policies into Qdrant (idempotent — safe to call on every run)
    print(f"\n[APG] Ingesting policies from {_POLICIES_PATH} ...")
    ingest_policies(_POLICIES_PATH)

    print(f"[APG] Processing request: {request_text!r}")
    result = asyncio.run(run_guardrail(request_text))
    _print_result(result)


if __name__ == "__main__":
    main()
