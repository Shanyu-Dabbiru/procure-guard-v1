# APG Implementation Prompts

Use these prompts one by one with your implementation agent (Copilot/Other). Ensure the agent has read `implementation_plan.md` and `policies.json` before starting.

---

### Task 1: Strict Data Models (`src/apg/schema.py`)
**Prompt:**
> Act as a Senior Python Engineer. Using the `implementation_plan.md` as your guide, implement `src/apg/schema.py`. 
> 
> You must:
> 1. Use Pydantic V2.
> 2. Implement `SpendIntent` using `Decimal` for the `amount` field to ensure financial precision.
> 3. Implement `Policy` and `ValidationResult` exactly as defined in the plan.
> 4. Ensure all fields have clear `Field` descriptions for LLM self-documentation.
> 5. Create the `src/apg` directory if it doesn't exist.

---

### Task 2: Knowledge Base & Hybrid Search (`src/apg/vector_db.py`)
**Prompt:**
> Act as a Vector DB Expert. Using `implementation_plan.md`, implement `src/apg/vector_db.py`.
> 
> You must:
> 1. Initialize a Qdrant client (use `:memory:` for local dev unless requested otherwise).
> 2. Implement logic to read `policies.json`, embed the rules using `OpenAIEmbeddings` (`text-embedding-3-small`), and upsert them into a collection named `corporate_policies`.
> 3. **CRITICAL:** The `retrieve_policies` function must implement **Hybrid Search** by applying a categorical filter on the Qdrant payload that matches the `SpendIntent.category`. This ensures we never miss a policy due to vector distance.
> 4. Return a list of `Policy` Pydantic models.

---

### Task 3: LangGraph Nodes (`src/apg/nodes.py`)
**Prompt:**
> Act as an Agentic Workflow Engineer. Using `implementation_plan.md`, implement `src/apg/nodes.py`.
> 
> You must:
> 1. Implement 4 functions: `extract_intent`, `retrieve_policies`, `validate_guardrails`, and `route_decision`.
> 2. `extract_intent` must use `with_structured_output(SpendIntent)` with a LangChain-compatible LLM.
> 3. `validate_guardrails` must be **100% deterministic Python logic**. No LLM should be used here. Loop through `retrieved_policies` and check if `SpendIntent.amount` exceeds the thresholds defined in the rule text (you may need a simple regex or parser for the "exceeding $X" strings in `policies.json`).
> 4. All nodes should take and return the `APGState`.

---

### Task 4: State Machine Orchestration (`src/apg/graph.py`)
**Prompt:**
> Act as a LangGraph Expert. Using `implementation_plan.md`, implement `src/apg/graph.py`.
> 
> You must:
> 1. Define the `APGState` TypedDict.
> 2. Use `StateGraph` to orchestrate the nodes from `src/apg/nodes.py`.
> 3. Implement the **Conditional Edge** `check_extraction`: if intent extraction fails or is refused by the LLM, route to a termination node that sets the decision to a "Dead Letter Queue" (DLQ) rejection.
> 4. Compile the graph and export it as an object named `app`.

---

### Task 5: entry Point & Observability (`src/apg/main.py`)
**Prompt:**
> Act as a DevOps & Observability Engineer. Using `implementation_plan.md`, implement `src/apg/main.py`.
> 
> You must:
> 1. Initialize `logfire` with the Pydantic plugin enabled for global tracing.
> 2. Create an async `main(query: str)` function that invokes the LangGraph `app`.
> 3. Wrap the whole execution in a `logfire.span` to ensure a single unified trace for the audit.
> 4. Set up a simple `if __name__ == "__main__":` block that takes a command-line argument as the natural language request.

---

### Task 6: Testing (`tests/test_apg.py`)
**Prompt:**
> Act as a QA Engineer. Implement a comprehensive test suite in `tests/test_apg.py`.
> 
> You must:
> 1. Test Pydantic validation (ensure `Decimal` precision works and strings fail for amount).
> 2. Mock the LLM and Vector DB to test the LangGraph state transitions.
> 3. Assert that a request for a "$3000 Laptop" correctly triggers the `Finance-VP-Queue` exception path according to `POL-001`.
