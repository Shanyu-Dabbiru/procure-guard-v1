# System Blueprint: Autonomous Procurement Guardrail (APG)

## Goal Description
Build the Autonomous Procurement Guardrail (APG) - a "Zero-Trust" decision firewall using Agent Operating Procedures (AOPs). The system will intercept procurement intents, validate them against corporate policy mapped from `policies.json`, and enforce rules (SOC2 requirements, spend approvals) before ERP execution.

## System Architecture Overview

1. **Intent Extraction Layer** 
   - Receives unstructured requests (e.g., Slack/Email text).
   - Extracts semantic elements (Vendor, Spend Category, Amount, Justification).
2. **Knowledge Retrieval Layer (Qdrant)**
   - Takes extracted intent and performs semantic search over `policies.json` vector embeddings.
   - Retrieves matching policies (e.g., POL-001 for Hardware, POL-002 for SaaS).
3. **Guardrail Validation Engine (Pydantic V2)**
   - Strict schema enforcement applied to the combination of Intent + Retreived Policy. 
   - Deterministic checks (e.g., Amount > $2500 & Category == Hardware).
4. **Decision & Routing (LangGraph)**
   - State-machine orchestrator.
   - Transitions between parsing, retrieval, validation, and final routing.
   - Outputs: `Approve`, `Reject`, or `Route to Exception Path`.
5. **Observability (Logfire)**
   - Pydantic Logfire instrumented across the entire LangGraph flow.
   - Every agentic step, LLM call, and validation outcome traces back for CFO-level audit.

## Verification Plan

### Automated Tests
- Unit testing the Pydantic schemas validating various good/bad payloads.
- Testing Qdrant retrieval with mock queries to ensure the correct policy is matched.
- Pytest standard suite to verify LangGraph state transitions.

### Manual Verification
- A custom CLI mock run script to ingest sample natural language spend requests and print out the complete Logfire trace and final routing decision.
