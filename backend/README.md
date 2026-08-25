# Backend — Multi-Agent Research Assistant

> FastAPI, Celery, PostgreSQL 16 (pgvector), Redis 7, and LangGraph.

The backend service and core execution engine for the Multi-Agent Research Assistant. It implements the multi-agent research pipeline, durable human-in-the-loop checkpointing, cryptographic BYOK storage, real-time SSE streaming, document corpus indexing, and offline bundle verification.

---

## Directory Structure

```
backend/
├── app/                    # FastAPI application & server runtime
│   ├── api/                # API route handlers (v1, auth, research, projects, chat)
│   ├── models/             # SQLAlchemy ORM models (PostgreSQL & pgvector)
│   ├── schemas/            # Pydantic request/response schemas
│   ├── services/           # Business logic (rate limiting, crypto, chat scope)
│   ├── workers/            # Celery application and task definitions
│   └── main.py             # FastAPI entrypoint
├── research_engine/        # Standalone, local-first LangGraph research engine
│   ├── graph.py            # LangGraph StateGraph and node definitions
│   ├── corpus.py           # Local document store, chunking & embeddings
│   ├── claims.py           # Canonical claim extraction and citation matching
│   ├── verify_bundle.py    # Standalone offline artifact verifier
│   └── ports.py            # Engine ports and dependency injection contracts
├── desktop/                # In-process sidecar driver for desktop/Tauri builds
├── evals/                  # Evaluation harness, judges, and benchmark results
├── alembic/                # Database migrations
└── tests/                  # Pytest unit, integration, and regression suites
```

---

## Architecture & Boundaries

1. **`research_engine/` Isolation:**
   The `research_engine` is a pure, local-first package that **never** imports `app` or `evals`. It interacts with database persistence, event publishers, and LLMs exclusively through dependency-injected ports (`ports.py`) and `RunConfig`.

2. **Durable Human Gates:**
   LangGraph checkpoints execution state into PostgreSQL (or SQLite on desktop). The graph pauses at real `interrupt()` gates (`design_gate` and `review_gate`) rather than polling loops, allowing workers to exit safely without wasting resources or double-spending token budgets.

3. **Strict Claim & Citation Integrity:**
   Claim extraction and citation regexes have a single authoritative home in `research_engine/claims.py`. Every cited `[n]` resolves to an exact source URL and verbatim snippet.

---

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL 16 with `pgvector`
- Redis 7

### Setup

```bash
# Set up virtual environment and install dependencies
make backend-setup

# Apply database migrations
make migrate

# Start FastAPI server
make backend-dev

# Start Celery worker (in a separate terminal)
make worker
```

---

## Running Tests & Evals

```bash
# Run all backend unit and integration tests
pytest

# Run fast unit tests only
pytest -m "not integration and not slow"

# Run report quality evaluation suite
make eval
```
