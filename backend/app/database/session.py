"""
Async SQLAlchemy engine + session factory.

Sprint 2 will add the actual models (Projects, Videos, Scripts, etc.)
and repositories that use `get_db`. This module just wires the
connection so migrations and the health check can run today.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

is_prod = (settings.app_env or "").lower() == "production"

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug and not is_prod,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session, always closes it."""
    async with AsyncSessionLocal() as session:
        yield session
