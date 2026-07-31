.PHONY: infra-up infra-down infra-clean backend-setup backend-dev worker migrate migration \
        frontend-setup frontend-dev frontend-build test test-backend test-frontend \
        lint format eval compose-up compose-down compose-logs help

## ─── Dev infrastructure (postgres + redis only; app runs natively) ──────────────
infra-up:
	docker compose up -d
	@echo "✅ PostgreSQL and Redis are running."

infra-down:
	docker compose down
	@echo "✅ Infrastructure stopped."

infra-clean:
	docker compose down -v
	@echo "✅ Infrastructure stopped and volumes removed."

## ─── Full stack (docs/09 §2): one command → the whole app ───────────────────────
compose-up:
	docker compose -f docker-compose.full.yml up --build -d
	@echo "✅ Full stack up. Frontend: http://localhost:$${FRONTEND_PORT:-3000}"

compose-down:
	docker compose -f docker-compose.full.yml down

compose-logs:
	docker compose -f docker-compose.full.yml logs -f

## ─── Backend ────────────────────────────────────────────────────────────────────
backend-setup:
	cd backend && python3.11 -m venv .venv && \
	. .venv/bin/activate && \
	pip install --upgrade pip && \
	pip install -r requirements.txt
	@echo "✅ Backend dependencies installed."

backend-dev:
	cd backend && . .venv/bin/activate && \
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd backend && . .venv/bin/activate && \
	celery -A app.workers.celery_app.celery_app worker --loglevel=info --concurrency=4

migrate:
	cd backend && . .venv/bin/activate && \
	alembic upgrade head
	@echo "✅ Database migrations applied."

migration:
	cd backend && . .venv/bin/activate && \
	alembic revision --autogenerate -m "$(msg)"

## ─── Frontend ───────────────────────────────────────────────────────────────────
frontend-setup:
	cd frontend && npm install
	@echo "✅ Frontend dependencies installed."

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

## ─── Quality ────────────────────────────────────────────────────────────────────
test: test-backend test-frontend

test-backend:
	cd backend && . .venv/bin/activate && \
	python -m pytest tests/ -v --tb=short

test-frontend:
	cd frontend && npm test

lint:
	cd backend && . .venv/bin/activate && ruff check app/ research_engine/ tests/ evals/
	cd frontend && npm run lint

format:
	cd backend && . .venv/bin/activate && ruff format app/ research_engine/ tests/ evals/ && ruff check --fix app/ research_engine/ tests/ evals/

## ─── Evals (docs/08 §5) ─────────────────────────────────────────────────────────
# Fake mode by default (deterministic, no keys). Real: LLM_MODE=real GOOGLE_API_KEY=… make eval
eval:
	cd backend && . .venv/bin/activate && python -m evals.harness

help:
	@grep -E '^[a-zA-Z_-]+:' Makefile | grep -v '.PHONY' | sed 's/:.*//' | sort | column
