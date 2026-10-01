# Guardrailed Queue Agent

A social media queue management agent built with **LangGraph**, **SQLite**, and **LangSmith**. It enforces structural safety guardrails around AI state mutations through **progressive autonomy** and **reversible actions (event-sourcing undo logs)**.

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

## Getting Started

### 1. Clone the Repository
```bash
git clone https://github.com/vikram0678/guardrailed-queue-agent.git
cd guardrailed-queue-agent
```

### 2. Configure Environment
```bash
cp .env.example .env
```
*(All tests and simulations run 100% offline and locally out-of-the-box. Adding OpenAI or OpenRouter keys in `.env` is optional for live model calling).*

---

## Method 1: Running with Docker (Recommended)

### 1. Build and Start Container
```bash
docker compose up --build -d
```

### 2. Check Container Health
```bash
docker compose ps
```

### 3. Run Unit Tests Inside Docker
```bash
docker compose exec app pytest -v tests/
```

### 4. Run Adversarial Safety Simulation Inside Docker
Simulates the Replit failure scenario with an untrusted agent ($N=0$) and ambiguous cleanup instruction:
```bash
docker compose exec app python tests/simulate_failure.py
```

### 5. Run Interactive Agent Inside Docker
```bash
# Seed the database
docker compose exec app python -m src.agent --seed

# Run instruction with live human-in-the-loop approval (type 'y' when prompted)
docker compose exec -it app python -m src.agent "Publish all pending posts"
```

### 6. Stop Container
```bash
docker compose down
```

---

## Method 2: Running Locally with Python Virtual Environment

### 1. Create and Activate Virtual Environment
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

### 3. Run Unit Tests
```bash
pytest -v tests/
```

### 4. Run Failure Simulation
```bash
python tests/simulate_failure.py
```

### 5. Interactive CLI Usage
```bash
# Seed sample posts
python -m src.agent --seed

# Run agent instruction
python -m src.agent "Publish all pending posts"

# Restore a record by action ID
python -m src.agent --restore <action_id_uuid>
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
