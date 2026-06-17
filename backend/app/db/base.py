from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator
import structlog

from app.config import settings
from app.models import Base  # noqa: F401 — imports all models for Alembic

logger = structlog.get_logger()

engine = create_async_engine(
    settings.database_url,
    echo=False,          # Set True for SQL query logging in development
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Reconnect if connection dropped
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def init_db() -> None:
    """Create all tables (dev only — use Alembic migrations in production)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("db_init", message="Database tables created/verified")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
