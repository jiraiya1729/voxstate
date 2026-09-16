"""Reusable event sinks for runtime components."""

from typing import Protocol

from app.db.database import Database
from app.events.envelope import EventCreate, EventEnvelope
from app.events.repository import EventRepository


class EventSink(Protocol):
    """Minimal async interface for components that emit normalized events."""

    async def append(self, event: EventCreate) -> EventEnvelope: ...


class NullEventSink:
    """No-op sink used where durable event capture is intentionally disabled."""

    async def append(self, event: EventCreate) -> EventEnvelope:
        raise RuntimeError("NullEventSink cannot persist events")


class DatabaseEventSink:
    """Append events through a fresh database transaction per runtime emission."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def append(self, event: EventCreate) -> EventEnvelope:
        async with self.database.session() as session:
            return await EventRepository(session).append(event)
