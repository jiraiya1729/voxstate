from uuid import uuid4

import pytest

from app.calls.lifecycle import (
    ProviderCallMismatchError,
    UnknownCallError,
)
from app.calls.lifecycle_service import CallLifecycleService
from app.calls.models import Call
from app.calls.repository import CallRepository
from app.db.database import Database
from app.events.repository import EventRepository


async def create_pending_call(database: Database) -> Call:
    async with database.session() as session:
        return await CallRepository(session).create(to_phone_number="+15555550120")


@pytest.mark.asyncio
async def test_early_callback_binds_provider_id_and_advances_status(
    database: Database,
) -> None:
    call = await create_pending_call(database)
    service = CallLifecycleService(database=database)

    status = await service.apply_status_callback(
        call_id=call.id,
        provider_call_id="CA00000000000000000000000000000020",
        provider_status="initiated",
    )

    assert status == "initiated"
    async with database.session() as session:
        stored = await CallRepository(session).get_by_id(call.id)
        events = await EventRepository(session).list_for_call(call.id)
    assert stored is not None
    assert stored.provider_call_id == "CA00000000000000000000000000000020"
    assert [event.event_type for event in events] == ["call.initiated"]
    assert events[0].payload["provider_status"] == "initiated"


@pytest.mark.asyncio
async def test_replayed_callback_is_idempotent(database: Database) -> None:
    call = await create_pending_call(database)
    service = CallLifecycleService(database=database)
    callback = {
        "call_id": call.id,
        "provider_call_id": "CA00000000000000000000000000000021",
        "provider_status": "ringing",
    }

    first = await service.apply_status_callback(**callback)
    second = await service.apply_status_callback(**callback)

    assert first == "ringing"
    assert second == "ringing"
    async with database.session() as session:
        events = await EventRepository(session).list_for_call(call.id)
    assert [event.event_type for event in events] == ["call.ringing"]


@pytest.mark.asyncio
async def test_unknown_internal_call_is_rejected(database: Database) -> None:
    service = CallLifecycleService(database=database)

    with pytest.raises(UnknownCallError):
        await service.apply_status_callback(
            call_id=uuid4(),
            provider_call_id="CA00000000000000000000000000000022",
            provider_status="ringing",
        )


@pytest.mark.asyncio
async def test_mismatched_provider_call_id_is_rejected(
    database: Database,
) -> None:
    call = await create_pending_call(database)
    service = CallLifecycleService(database=database)
    await service.apply_status_callback(
        call_id=call.id,
        provider_call_id="CA00000000000000000000000000000023",
        provider_status="ringing",
    )

    with pytest.raises(ProviderCallMismatchError):
        await service.apply_status_callback(
            call_id=call.id,
            provider_call_id="CA00000000000000000000000000000024",
            provider_status="completed",
        )
