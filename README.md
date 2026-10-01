# Guardrailed Queue Management Agent

A reliable social media queue management agent built with **LangGraph**, **SQLite**, and **LangSmith**. It enforces structural safety guardrails around AI state mutations through **progressive autonomy** and **reversible actions (event-sourcing undo logs)**.

---

## Why This Exists

Prompt-based guardrails (e.g. telling an LLM *"please don't delete rows during code freeze"*) are advisory and statistically prone to hallucination under pressure—as seen in the July 2025 SaaStr/Replit database incident.

This project implements code-level safety guarantees:
1. **Physical Decoupling**: The planning node proposes actions, but cannot execute SQL directly.
2. **Progressive Autonomy (Trust Gate)**: Low-trust mutations ($< 3$ approvals) trigger a hard physical pause (`interrupt()`) requiring human approval before execution.
3. **Pre-Mutation Event Sourcing**: Full row snapshots are written to `action_log` as JSON *before* any `DELETE` or `UPDATE` is applied.
4. **Deterministic Restore**: `restore_from_log(action_id)` blindly recovers deleted or modified rows with 100% fidelity, bypassing the LLM entirely.

---

## Project Structure

```text
guardrailed-queue-agent/
├── docker-compose.yml       # Container setup with live volume mount
├── Dockerfile               # Python 3.11-slim container definition
├── .env.example             # Configuration template
├── requirements.txt         # Project dependencies
├── README.md                # Documentation & usage guide
├── premortem.md             # Incident analysis on advisory guardrail failures
├── postmortem.md            # Analysis of adversarial failure simulation
├── src/
│   ├── database.py          # SQLite schema (content_queue, action_log, trust_metrics)
│   ├── operations.py        # Reversible mutations and restore_from_log logic
│   ├── schemas.py           # Pydantic tool schemas and graph state
│   ├── graph.py             # LangGraph state machine & trust gate routing
│   └── agent.py             # CLI runner and interactive execution harness
└── tests/
    ├── test_restore.py      # Pytest unit tests for logging & rollback
    └── simulate_failure.py  # Adversarial simulation asserting state machine pause
```

---

## Quickstart (Local Setup)

### 1. Set Up Virtual Environment
```bash
# Windows
python -m venv .venv
source .venv/Scripts/Activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
```
*(Tests run 100% locally and offline. Adding OpenAI or OpenRouter keys in `.env` is optional for live model calling).*

---

## Running the Tests

### Unit Tests (Schema, Logging & Rollback)
```bash
pytest -v tests/
```

### Adversarial Failure Simulation
Simulates the Replit disaster with an untrusted agent ($N=0$) and ambiguous cleanup instruction:
```bash
python tests/simulate_failure.py
```

---

## CLI & Interactive Usage

### 1. Seed Sample Posts
```bash
python -m src.agent --seed
```

### 2. Run an Instruction (Interactive HITL Pause)
```bash
python -m src.agent "Publish all pending posts"
```
If trust is below threshold ($N < 3$), the CLI pauses and prompts:
```text
[APPROVAL REQUIRED] Action approval required for: [...]
Proceed? (Y/N): 
```
Type `Y` to approve or `N` to reject.

### 3. Restore a Mutated Record
```bash
python -m src.agent --restore <action_id_uuid>
```

---

## Docker Execution

```bash
# Build and run container in background
docker-compose up --build -d

# Run pytest inside container
docker-compose exec app pytest tests/

# Run simulation inside container
docker-compose exec app python tests/simulate_failure.py

# Stop container
docker-compose down
```

---

## Observability (LangSmith)

To view execution traces on [smith.langchain.com](https://smith.langchain.com):
1. Add your free LangSmith key to `.env`:
   ```ini
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=lsv2_pt_...
   LANGCHAIN_PROJECT=guardrail_agent
   ```
2. Run any command—traces will stream to your dashboard automatically.
