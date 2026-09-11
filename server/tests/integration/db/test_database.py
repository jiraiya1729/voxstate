import pytest
from sqlalchemy import select, text

from app.calls.models import Call
from app.calls.repository import CallRepository
from app.db.database import Database


@pytest.mark.asyncio
async def test_migration_is_at_expected_revision(
    database: Database,
) -> None:
    async with database.session() as session:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))

    assert result.scalar_one() == "0002_call_failure"


@pytest.mark.asyncio
async def test_database_connectivity(database: Database) -> None:
    assert await database.ping() is True


@pytest.mark.asyncio
async def test_successful_transaction_is_committed(
    database: Database,
) -> None:
    async with database.session() as session:
        created = await CallRepository(session).create(to_phone_number="+15555550101")
        call_id = created.id

    async with database.session() as session:
        stored = await CallRepository(session).get_by_id(call_id)

    assert stored is not None
    assert stored.to_phone_number == "+15555550101"
    assert stored.status == "pending"


@pytest.mark.asyncio
async def test_failed_transaction_is_rolled_back(
    database: Database,
) -> None:
    call_id = None

    with pytest.raises(RuntimeError, match="force rollback"):
        async with database.session() as session:
            created = await CallRepository(session).create(
                to_phone_number="+15555550102"
            )
            call_id = created.id
            raise RuntimeError("force rollback")

    assert call_id is not None

    async with database.session() as session:
        stored = await CallRepository(session).get_by_id(call_id)

    assert stored is None


@pytest.mark.asyncio
async def test_repository_creates_and_reads_call(
    database: Database,
) -> None:
    async with database.session() as session:
        created = await CallRepository(session).create(to_phone_number="+15555550103")

    async with database.session() as session:
        stored = await CallRepository(session).get_by_id(str(created.id))

    assert stored is not None
    assert stored.id == created.id


@pytest.mark.asyncio
async def test_repository_returns_none_for_invalid_id(
    database: Database,
) -> None:
    async with database.session() as session:
        stored = await CallRepository(session).get_by_id("not-a-uuid")

    assert stored is None


@pytest.mark.asyncio
async def test_database_fixture_hides_uncommitted_test_data(
    database: Database,
) -> None:
    async with database.session() as session:
        created = await CallRepository(session).create(to_phone_number="+15555550104")

    async with database.engine.connect() as observer:
        result = await observer.execute(select(Call.id).where(Call.id == created.id))

    assert result.scalar_one_or_none() is None
