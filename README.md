# Multi-Agent Research Assistant

> Production-grade, horizontally scalable research synthesis system powered by LangGraph multi-agent orchestration.

---

## Tech Stack
- **Frontend**: Next.js 14 (App Router), TailwindCSS, Zustand, TanStack Query
- **Backend**: FastAPI (Python 3.11+), LangGraph, LangChain
- **LLM Providers**: OpenAI GPT-4o (primary) + Google Gemini 1.5 Flash (Critic agent)
- **Search**: DuckDuckGo Search (free, no API key required)
- **Database**: PostgreSQL 15 (async SQLAlchemy + Alembic)
- **Cache/Queue**: Redis 7 (Celery broker, SSE pub/sub, distributed locks)
- **Infrastructure**: Docker Compose (local), Kubernetes (production)

## Project Structure

```
Multi-Agent Research Assistant/
├── backend/              # FastAPI backend + LangGraph agents
├── frontend/             # Next.js 14 frontend
├── multi_agent_docs/     # Project specification documents
├── docker-compose.yml    # Local development services
├── Makefile              # Developer convenience commands
└── README.md
```

## Quick Start

### Prerequisites
- Docker Desktop
- Python 3.11+
- Node.js 18+
- OpenAI API Key
- Google API Key (Gemini)

### Setup

```bash
# 1. Clone and enter the project
cd "Multi-Agent Research Assistant"

# 2. Copy environment file
cp .env.example .env
# Edit .env and add your API keys

# 3. Start infrastructure (Postgres + Redis)
make infra-up

# 4. Install and run backend
make backend-setup
make migrate
make backend-dev

# 5. Install and run frontend (new terminal)
make frontend-setup
make frontend-dev
```

The app will be running at:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

### Makefile Commands

```bash
make infra-up        # Start PostgreSQL + Redis via Docker Compose
make infra-down      # Stop infrastructure containers
make backend-setup   # Create venv and install Python dependencies
make backend-dev     # Run FastAPI dev server (with hot reload)
make worker          # Start Celery agent worker
make migrate         # Run Alembic migrations
make frontend-setup  # Install Node dependencies
make frontend-dev    # Run Next.js dev server
make test            # Run all tests
make lint            # Run ruff (Python) + eslint (JS)
```

## Environment Variables

See `.env.example` for all required variables.

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API key for GPT-4o |
| `GOOGLE_API_KEY` | ✅ | Google API key for Gemini 1.5 Flash |
| `DATABASE_URL` | ✅ | PostgreSQL async connection string |
| `REDIS_URL` | ✅ | Redis connection string |
| `JWT_SECRET_KEY` | ✅ | Secret for signing JWT tokens |
| `LANGCHAIN_API_KEY` | ⚪ | Optional: LangSmith for LLM tracing |

## Reference Documentation

All detailed specifications are in [`multi_agent_docs/`](./multi_agent_docs/):

1. [DOs and DON'Ts](./multi_agent_docs/1_DOs_and_DONTs.md) — Development guardrails
2. [System Architecture](./multi_agent_docs/2_System_Architecture.md) — Full system design
3. [UI/UX Guidelines](./multi_agent_docs/3_UIUX_Guidelines.md) — Frontend component specs
4. [Domain Context](./multi_agent_docs/4_Domain_Context.md) — Business context & personas
5. [Roadmap](./multi_agent_docs/5_Roadmap.md) — Development milestones
6. [Data Models & API](./multi_agent_docs/6_Database_Data_Models.md) — DB schema & API contracts
7. [Agent Prompts & Tools](./multi_agent_docs/7_Prompts_and_Tools.md) — LLM prompt specs
