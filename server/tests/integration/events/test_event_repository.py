import pytest

from app.calls.repository import CallRepository
from app.db.database import Database
from app.events.envelope import EventCreate
from app.events.repository import EventRepository


@pytest.mark.asyncio
async def test_event_repository_appends_ordered_call_history(
    database: Database,
) -> None:
    async with database.session() as session:
        call = await CallRepository(session).create(to_phone_number="+15555550200")
        repository = EventRepository(session)

        first = await repository.append(
            EventCreate(
                event_type="call.requested",
                call_id=call.id,
                payload={"to_phone_number": call.to_phone_number},
            )
        )
        second = await repository.append(
            EventCreate(
                event_type="call.ringing",
                call_id=call.id,
                payload={"status": "ringing"},
            )
        )

    async with database.session() as session:
        events = await EventRepository(session).list_for_call(call.id)

    assert [event.sequence for event in events] == [1, 2]
    assert [event.event_type for event in events] == [
        "call.requested",
        "call.ringing",
    ]
    assert first.sequence == 1
    assert second.sequence == 2


@pytest.mark.asyncio
async def test_event_repository_returns_existing_idempotent_event(
    database: Database,
) -> None:
    async with database.session() as session:
        call = await CallRepository(session).create(to_phone_number="+15555550201")
        repository = EventRepository(session)
        first = await repository.append(
            EventCreate(
                event_type="call.ringing",
                call_id=call.id,
                idempotency_key="twilio-status-1",
                payload={"status": "ringing"},
            )
        )
        second = await repository.append(
            EventCreate(
                event_type="call.ringing",
                call_id=call.id,
                idempotency_key="twilio-status-1",
                payload={"status": "ringing"},
            )
        )

    assert second.id == first.id
    assert second.sequence == 1

    async with database.session() as session:
        events = await EventRepository(session).list_for_call(call.id)

    assert len(events) == 1
