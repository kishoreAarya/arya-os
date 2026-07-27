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

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
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
