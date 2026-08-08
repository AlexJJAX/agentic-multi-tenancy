"""
SQLite database connection and session management.

Uses SQLAlchemy async engine with aiosqlite for all database operations.
Tables are created automatically on first initialization.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)

# Async engine for all database operations
engine = create_async_engine(
    settings.sqlite_url,
    echo=False,
    # SQLite-specific: allow multiple concurrent readers
    connect_args={"check_same_thread": False},
)

# Session factory for creating new database sessions
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an async database session context manager.

    Usage:
        async with get_db_session() as session:
            result = await session.execute(...)
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """
    Initialize the database by creating all tables if they do not exist.

    Called during application startup to ensure the database schema is ready.
    """
    from app.models import Base  # Import here to avoid circular imports

    # Ensure the data directory exists
    from pathlib import Path

    db_path = Path(settings.sqlite_path)
    if not db_path.is_absolute():
        from app.config import PROJECT_ROOT
        db_path = PROJECT_ROOT / db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        # Enable WAL mode for better concurrent read performance
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        # Enable foreign keys
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database initialized at %s", settings.sqlite_path)


async def check_db_health() -> str:
    """
    Check database connectivity by running a simple query.

    Returns:
        "ok" if the database is accessible, "error" otherwise.
    """
    try:
        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        return "error"
