.PHONY: infra-up infra-down backend-setup backend-dev worker migrate frontend-setup frontend-dev test lint

## ─── Infrastructure ────────────────────────────────────────────────────────────
infra-up:
	docker-compose up -d
	@echo "✅ PostgreSQL and Redis are running."

infra-down:
	docker-compose down
	@echo "✅ Infrastructure stopped."

infra-clean:
	docker-compose down -v
	@echo "✅ Infrastructure stopped and volumes removed."

## ─── Backend ───────────────────────────────────────────────────────────────────
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
	celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

migrate:
	cd backend && . .venv/bin/activate && \
	alembic upgrade head
	@echo "✅ Database migrations applied."

migration:
	cd backend && . .venv/bin/activate && \
	alembic revision --autogenerate -m "$(msg)"

## ─── Frontend ──────────────────────────────────────────────────────────────────
frontend-setup:
	cd frontend && npm install
	@echo "✅ Frontend dependencies installed."

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

## ─── Quality ───────────────────────────────────────────────────────────────────
test:
	cd backend && . .venv/bin/activate && \
	pytest tests/ -v --tb=short

lint:
	cd backend && . .venv/bin/activate && ruff check app/ tests/
	cd frontend && npx eslint src/

## ─── Helpers ───────────────────────────────────────────────────────────────────
check-secrets:
	@echo "Checking for hardcoded secrets..."
	@grep -rn "sk-" backend/app/ && echo "⚠️  Possible OpenAI key found!" || echo "✅ No OpenAI keys found."
	@grep -rn "sk-ant" backend/app/ && echo "⚠️  Possible Anthropic key found!" || echo "✅ No Anthropic keys found."
