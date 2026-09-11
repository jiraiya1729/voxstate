import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.database import Database, create_database_engine

DEFAULT_TEST_DATABASE_URL = (
    "postgresql://postgres:postgres@localhost:5433/voxstate_test"
)


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    database_url = os.getenv(
        "VOXSTATE_TEST_DATABASE_URL",
        DEFAULT_TEST_DATABASE_URL,
    )
    database_name = make_url(database_url).database

    if database_name is None or not database_name.endswith("_test"):
        raise pytest.UsageError(
            "VOXSTATE_TEST_DATABASE_URL must target a database ending in '_test'"
        )

    project_directory = Path(__file__).parents[1]
    alembic_config = Config(project_directory / "alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")

    return database_url


@pytest_asyncio.fixture
async def database(
    migrated_database_url: str,
) -> AsyncIterator[Database]:
    engine = create_database_engine(migrated_database_url)

    async with engine.connect() as connection:
        transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        database = Database(engine, session_factory)

        try:
            yield database
        finally:
            if transaction.is_active:
                await transaction.rollback()

    await engine.dispose()
