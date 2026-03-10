# Autonomous Procurement Guardrail (APG) 🛡️

### **Mission: Eliminating Liability in Autonomous Enterprise Execution**

As enterprises transition from "Copilots" to **Autonomous AI Workforces**, the primary bottleneck is **compliance risk**. The APG is a high-performance middleware layer designed for agentic platforms like **Lio**. It intercepts autonomous purchase intents and validates them against complex corporate policies (SOC2, Spend Limits, Vendor Vetting) before any ERP execution occurs.



---

## 🚀 Why This Matters for Lio's $30M Series A
Lio's **Agent Operating Procedures (AOPs)** require a "Zero-Trust" architecture to scale in the US market. This project solves the **"Rogue Agent"** problem by providing:
- **Deterministic Compliance:** Moving beyond vague "system prompts" to strict Pydantic-enforced validation.
- **Audit-Ready Observability:** Full decision-traceability using Pydantic Logfire.
- **Enterprise Scale:** Distributed policy retrieval using Qdrant vector embeddings.

---

## 🛠️ The Tech Stack
- **Orchestration:** [LangGraph](https://github.com/langchain-ai/langgraph) (State-machine for cyclic agent workflows).
- **Validation:** [Pydantic V2](https://docs.pydantic.dev/) (Strict schema enforcement for "Safe-to-Execute" payloads).
- **Knowledge Base:** [Qdrant](https://qdrant.tech/) (Semantic retrieval of procurement laws and vendor white-lists).
- **Observability:** [Pydantic Logfire](https://logfire.pydantic.dev/) (Uncompromising audit trails for CFO/Security reviews).

---

## 🧠 Architectural Overview
The system follows a **"Guardrail-First"** design pattern:
1. **Intent Extraction:** Parsers convert messy Slack/Email inputs into structured Pydantic models.
2. **Policy Retrieval:** A RAG-based lookup identifies relevant corporate constraints based on the commodity code and amount.
3. **Multi-Agent Validation:** Specialized LangGraph nodes check for "Split-Ordering" attempts and "Unvetted Vendor" risks.
4. **ERP Interface:** A high-fidelity mock of a **SAP OData API** for end-to-end transaction testing.



---

## 🧪 Battle-Tested Logic (Stress Test Cases)
The system is verified against a custom test suite of common procurement bypass attempts:
- **The Splitter:** Detecting attempts to break a $5,000 order into two $2,500 orders to bypass VP approval.
- **The Shadow Vendor:** Flagging urgent requests for non-SOC2 compliant software.
- **The Obfuscator:** Catching vague commodity descriptions intended to hide personal spend.

---

## 🚦 Getting Started
1. `pip install -r requirements.txt`
2. `docker-compose up qdrant`
3. `python ingest_policies.py`
4. `python run_demo.py --case splitter_attack`

---
*Created by Shanyu Dabbiru - 2026 SF AI/Data Engineering Sprint*
