"""Async SQLAlchemy database wrapper for Supabase/Postgres.

This file creates async engines, normalizes Postgres URLs, opens transaction-scoped
sessions, runs lightweight pings, and disposes pooled connections.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def to_async_database_url(database_url: str) -> str:
    """Normalize Postgres URLs to the asyncpg SQLAlchemy driver scheme."""
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url

    if database_url.startswith("postgresql://"):
        return database_url.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )

    if database_url.startswith("postgres://"):
        return database_url.replace(
            "postgres://",
            "postgresql+asyncpg://",
            1,
        )

    raise ValueError("Database URL must use a PostgreSQL scheme")


def create_database_engine(database_url: str) -> AsyncEngine:
    """Create the async SQLAlchemy engine used for Supabase/Postgres access."""
    return create_async_engine(
        to_async_database_url(database_url),
        pool_pre_ping=True,
    )


class Database:
    """Small wrapper around the async engine and transaction-scoped sessions."""

    def __init__(
        self,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.engine = engine
        self.session_factory = session_factory

    @classmethod
    def from_url(cls, database_url: str) -> "Database":
        """Build a Database wrapper from the configured Postgres connection URL."""
        engine = create_database_engine(database_url)
        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )
        return cls(engine, session_factory)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Open a session, commit on success, and roll back on failure."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def ping(self) -> bool:
        """Run a lightweight connectivity check against the database."""
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True

    async def close(self) -> None:
        """Dispose pooled database connections during application shutdown."""
        await self.engine.dispose()
