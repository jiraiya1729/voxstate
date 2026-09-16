"""Database append/query operations for the event ledger."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.envelope import EventCreate, EventEnvelope
from app.events.models import Event


class EventRepository:
    """Append-only event repository scoped to a service-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, event: EventCreate) -> EventEnvelope:
        """Append one event, returning an existing row for repeated idempotency keys."""
        if event.idempotency_key is not None:
            existing = await self.get_by_idempotency_key(event.idempotency_key)
            if existing is not None:
                return existing

        sequence = await self._next_sequence(event.call_id)
        row = Event(
            event_type=event.event_type,
            call_id=event.call_id,
            sequence=sequence,
            correlation_id=event.correlation_id,
            idempotency_key=event.idempotency_key,
            version=event.version,
            payload=event.payload,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return EventEnvelope.model_validate(row)

    async def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> EventEnvelope | None:
        result = await self.session.execute(
            select(Event).where(Event.idempotency_key == idempotency_key)
        )
        row = result.scalar_one_or_none()
        return EventEnvelope.model_validate(row) if row is not None else None

    async def list_for_call(self, call_id: UUID) -> list[EventEnvelope]:
        result = await self.session.execute(
            select(Event)
            .where(Event.call_id == call_id)
            .order_by(Event.sequence.asc(), Event.occurred_at.asc())
        )
        return [EventEnvelope.model_validate(row) for row in result.scalars()]

    async def _next_sequence(self, call_id: UUID | None) -> int | None:
        if call_id is None:
            return None
        result = await self.session.execute(
            select(func.coalesce(func.max(Event.sequence), 0)).where(
                Event.call_id == call_id
            )
        )
        return int(result.scalar_one()) + 1
