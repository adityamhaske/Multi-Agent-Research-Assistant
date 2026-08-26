from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.config import settings
from app.db.base import engine
from app.db.redis import close_redis_pool, get_redis, init_redis_pool
from app.logconfig import configure_logging
from app.runtime import install_process_default
from app.services.security_headers import SecurityHeadersMiddleware
from research_engine.llm_factory import validate_pricing

# Configure structlog before the first log line: merge_contextvars is what lets a
# run's correlation_id ride along every log across the API → Celery → engine path.
configure_logging(json_output=settings.is_production)

logger = structlog.get_logger()

#: The application version, reported by the OpenAPI document and by `/health`.
#:
#: One constant rather than two literals: these were written out separately and drifted —
#: both still said `1.0.0` through the whole 1.0.x line, so `/health` reported a version the
#: deployment had not been running for two releases. Bump this with `desktop/tauri.conf.json`
#: and `frontend/lib/releases.ts` when cutting a tag.
APP_VERSION = "2.0.1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle.

    Schema is owned by Alembic — there is deliberately no create_all here
    (docs/03, docs/05 §2). Config is validated fast at import; pricing is
    re-checked here so a mis-routed model fails before serving traffic.

    The engine's RunConfig is installed before anything reads it: `research_engine` no
    longer imports `app.config` (docs/13 §2), so the host must supply it.
    """
    logger.info("startup", message="Starting Multi-Agent Research Assistant API")
    install_process_default()
    validate_pricing()
    await init_redis_pool()
    logger.info("startup", message="Redis initialized ✅ (run `alembic upgrade head` for schema)")
    yield
    await close_redis_pool()
    logger.info("shutdown", message="Server shutting down")


app = FastAPI(
    title="Multi-Agent Research Assistant API",
    version=APP_VERSION,
    description="Self-hostable research assistant with an auditable human-in-the-loop gate.",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)

# Dev convenience only: the browser talks to the API through the Next.js same-origin
# proxy in real deployments (docs/02 §1), so CORS is unnecessary there. In dev the
# frontend runs on a separate port, so we allow exactly that origin. In production
# no cross-origin browser access is permitted (docs/06 §6).
if not settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

# Mount versioned API router
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness — the process is up. Used by the container HEALTHCHECK."""
    return {"status": "ok", "version": APP_VERSION}


@app.get("/health/ready", tags=["Health"])
async def readiness_check():
    """Readiness — dependencies reachable (docs/09 §7). Compose gates the worker and
    frontend on this via `depends_on: condition: service_healthy`, so migrations and
    Redis are confirmed before dependents start. Returns 503 until both are up."""
    checks = {"database": False, "redis": False}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:  # noqa: BLE001
        logger.warning("readiness_db_down", error=str(e))
    try:
        await get_redis().ping()
        checks["redis"] = True
    except Exception as e:  # noqa: BLE001
        logger.warning("readiness_redis_down", error=str(e))

    if not all(checks.values()):
        return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})
    return {"status": "ready", "checks": checks}
