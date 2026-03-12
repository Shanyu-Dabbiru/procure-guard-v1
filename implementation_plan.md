# Autonomous Procurement Guardrail (APG) - Technical Design

## Goal Description
Build the Autonomous Procurement Guardrail (APG) - a "Zero-Trust" decision firewall using Agent Operating Procedures (AOPs). The system will intercept procurement intents, validate them against corporate policy mapped from `policies.json`, and enforce rules (SOC2 requirements, spend approvals) before ERP execution.

## User Review Required
> [!IMPORTANT]
> The architecture has been upgraded to "Auditor-Grade" per the review agent's feedback. Key changes include:
> - **Financial Precision**: Using `Decimal` instead of `float` for all currency amounts.
> - **Zero-Hallucination Validation**: The validation node is now 100% Python logic (no LLM) to ensure deterministic auditability.
> - **Hybrid Search**: Enforced hard category filtering in Qdrant to prevent missing policies.
> - **Error Resilience**: Added a DLQ (Dead Letter Queue) path for failed intent extraction.

## Proposed Changes

### 1. File Structure and Modules
- **`src/apg/schema.py`**: All Pydantic V2 definitions for strict type-checking and validation. This is our "Bouncer".
- **`src/apg/vector_db.py`**: Qdrant connection management, policy embedding creation, and semantic search retrieval. This is our "Law Library".
- **`src/apg/nodes.py`**: Individual operational functions for the LangGraph state machine.
- **`src/apg/graph.py`**: The LangGraph `StateGraph` compilation and routing logic. This is our "Traffic Cop".
- **`src/apg/main.py`**: Entry point scripting and Pydantic Logfire setup.

---

### 2. Guardrail Validation Engine (`schema.py`)
We rely on Pydantic V2 for strict payload enforcement.

```python
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional

class SpendIntent(BaseModel):
    vendor: str = Field(description="Name of the vendor being purchased from")
    category: Literal["Hardware", "Software/SaaS", "Vendor Management", "General Spend", "AI/Cloud", "Unknown"] = Field(description="The procurement category")
    amount: Decimal = Field(description="The total continuous amount in USD (using Decimal to prevent float rounding errors)", gt=Decimal('0.00'))
    justification: str = Field(description="Reason for the purchase")

class Policy(BaseModel):
    id: str
    category: str
    rule: str
    exception_path: str

class ValidationResult(BaseModel):
    is_compliant: bool = Field(description="True if the intent passes all retrieved policies")
    reason: str = Field(description="Detailed reason for approval or rejection")
    exception_workflow: Optional[str] = Field(None, description="The exception path if rejected")
```

---

### 3. Knowledge Retrieval Layer (`vector_db.py`)
Qdrant will store our local policies (`policies.json`). 

- **Initialization**: Upon system start (or run script), `vector_db.py` reads `policies.json`.
- **Embedding**: We will use LangChain's `OpenAIEmbeddings` (specifically `text-embedding-3-small` or `text-embedding-ada-002`) to convert the policy `rule` text into vector space.
- **Collection**: We will define a Qdrant collection named `corporate_policies`.
- **Payload Schema**: Each vector point will store the raw `Policy` dictionary (id, category, rule, exception_path) in its payload.
- **Retrieval Engine**: A `retrieve_policies(intent: SpendIntent) -> list[Policy]` function embeds the incoming request and performs a similarity search. **CRITICAL**: It must implement Hard Filtering (Hybrid Search) on Qdrant payloads matching the intent's `category` to guarantee no categorical policy rules are missed due to vector distance.

---

### 4. Decision & Routing (`graph.py` & `nodes.py`)
LangGraph ensures deterministic execution. 

#### State Schema (`APGState`)
```python
from typing import TypedDict, Optional, List

class APGState(TypedDict):
    request_text: str
    extracted_intent: Optional[dict] # Dict representing SpendIntent
    retrieved_policies: List[dict]   # List of Dict representing Policy
    validation_result: Optional[dict]# Dict representing ValidationResult
    final_decision: str              # "Approve", "Reject", "Exception: <path>"
```

#### Graph Nodes (`nodes.py`)
1. **`extract_intent(state: APGState) -> APGState`**: 
   - Takes `request_text`.
   - Calls an LLM (e.g., `gpt-4o-mini` using `langchain-openai`) instructing it to use `with_structured_output(SpendIntent)`.
   - Saves the dict format to `extracted_intent` in the state.
2. **`retrieve_policies(state: APGState) -> APGState`**: 
   - Uses `extracted_intent` to call `vector_db.retrieve_policies`.
   - Saves matched policies to `retrieved_policies`.
3. **`validate_guardrails(state: APGState) -> APGState`**: 
   - A **100% deterministic node**. It takes the `extracted_intent` and `retrieved_policies`.
   - **ZERO LLM INVOLVEMENT**. Uses strict python logic to determine if the intent violates the policies by checking thresholds. If so, it reads the `exception_path` from the violated policy.
   - Saves the structured response as `validation_result`.
4. **`route_decision(state: APGState) -> APGState`**: 
   - Analyzes `validation_result`. Sets `final_decision` to standard output (e.g., `Approve` or `Exception: Route to Finance-VP-Queue`).

#### Edges/Transitions (`graph.py`)
- `START` -> `extract_intent`
- `extract_intent` -> Conditional Edge (`check_extraction`)
  - If extraction successful -> `retrieve_policies`
  - If extraction failed/refused -> `route_to_dlq` (Dead Letter Queue rejection)
- `retrieve_policies` -> `validate_guardrails`
- `validate_guardrails` -> `route_decision`
- `route_decision` -> `END`

---

### 5. Observability (`main.py`)
- Install via `import logfire`.
- Configure `logfire.configure(pydantic_plugin=logfire.PydanticPlugin(record="all"))` right at system start.
- Wrap LangGraph executions in Logfire context managers so we get a single, unified CFO-level audit trace for every request.

## Verification Plan

### Automated Tests (`tests/`)
- `test_schemas.py`: Verify that passing "one hundred" dollars fails Pydantic validation, while `100.0` succeeds.
- `test_vector_db.py`: Insert dummy policies into a local in-memory Qdrant and assert that querying for "SaaS purchase" returns `POL-002`.
- `test_graph.py`: Mock the LLM and Qdrant calls to ensure the state machine moves exactly through `extract -> retrieve -> validate -> route`.

### Manual CLI Run
The primary artifact will be a runnable script:
```bash
python -m src.apg.main "Buy 50 MacBooks from Apple for $100,000 to supply new engineering hires"
```
The output should:
1. Print the extracted `SpendIntent` (showing `$2500` threshold triggered).
2. Print the retrieved `POL-001`.
3. Print final decision: `Exception: Route to Finance-VP-Queue`.
4. Provide a Logfire UI link verifying the entire trace.
