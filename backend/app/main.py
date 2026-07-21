from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.db.base import init_db
from app.db.redis import close_redis_pool, init_redis_pool

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("startup", message="Starting Multi-Agent Research Assistant API")
    await init_db()
    await init_redis_pool()
    logger.info("startup", message="Database and Redis initialized ✅")
    yield
    await close_redis_pool()
    logger.info("shutdown", message="Server shutting down")


app = FastAPI(
    title="Multi-Agent Research Assistant API",
    version="1.0.0",
    description="Self-hostable research assistant with an auditable human-in-the-loop gate.",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    lifespan=lifespan,
)

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
    return {"status": "ok", "version": "1.0.0"}
