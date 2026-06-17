# Multi-Agent Research Assistant

> Production-grade, horizontally scalable research synthesis system powered by LangGraph multi-agent orchestration.

---

## Why Use This Project? (The Edge)
Unlike standard single-prompt LLM wrappers, the **Multi-Agent Research Assistant** delegates tasks to a specialized team of autonomous AI agents. This guarantees deeper dives, hallucination-free fact-checking, and comprehensive synthesis that closely mimics a real human research team.
- **Save Hours of Manual Work:** Turn days of manual googling, reading, and summarizing into a 3-minute automated pipeline.
- **Cost-Efficient & Scalable:** Uses Gemini 1.5 Flash for rapid, cheap critiques and Gemini 1.5 Pro for deep reasoning, ensuring enterprise-grade performance without the massive API bills.
- **Human-in-the-Loop (HITL):** You aren't just handed a black-box result. You can intervene, review drafts, and ask the agents to rework specific sections before the final report is generated.

## Exceptional Functions & Features
- 🧠 **Multi-Agent Orchestration (LangGraph):** A cyclical graph of agents (Planner, Executor, Critic, Synthesizer). The Executor gathers data, the Critic reviews it against your prompt, and if it's not good enough, sends it back to the Executor.
- 💬 **Contextual Follow-Up Chat:** Once a report is generated, chat directly with the final document. The AI retains full context of the research session, allowing you to interrogate the data interactively.
- ⏳ **Real-Time Live Feed:** Watch the "brain" of the AI at work. An EventSource (SSE) stream provides a live feed of exactly what each agent is thinking and doing in real-time.
- 🌓 **Modern UI/UX:** A stunning, responsive Next.js frontend with dark/light mode toggles, interactive markdown rendering, and animated status monitors.

## How to Use the Application
1. **Create an Account/Login:** Secure JWT-based authentication ensures your research history is private.
2. **Start a Research Session:** Head to the Dashboard. Enter a detailed prompt (e.g., *"Analyze the competitive landscape of AI coding assistants in Q4 2024"*). Choose your research depth and click start.
3. **Monitor the Agents:** Watch the Live Feed as the Planner breaks down the task, the Executor searches the web, and the Critic evaluates the findings.
4. **Human Review (Awaiting Approval):** Review the Draft Report. You can either hit "Approve" to generate the final Markdown document, or "Reject & Rework" with specific feedback to send the agents back to work.
5. **Chat with the Report:** Once completed, view the final report and use the adjacent Chat Panel to ask follow-up questions.
6. **Browse History:** Access your past research sessions, review costs and durations, and pick up where you left off via the History dashboard.

---

## Tech Stack
- **Frontend**: Next.js 14 (App Router), TailwindCSS v4, Zustand, TanStack Query
- **Backend**: FastAPI (Python 3.11+), LangGraph, LangChain
- **LLM Providers**: Google Gemini 1.5 Pro (Reasoning) + Gemini 1.5 Flash (Chat/Critique)
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
