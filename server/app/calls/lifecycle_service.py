"""Database-backed call lifecycle service.

This file applies signed Twilio status callbacks to persisted calls using the pure
lifecycle transition rules.
"""

from uuid import UUID

from app.calls.lifecycle import UnknownCallError, resolve_call_transition
from app.calls.repository import CallRepository
from app.db.database import Database
from app.events.envelope import EventCreate
from app.events.repository import EventRepository


class CallLifecycleService:
    """Applies signed provider lifecycle callbacks to persisted call state."""

    def __init__(self, *, database: Database) -> None:
        self.database = database

    async def apply_status_callback(
        self,
        *,
        call_id: UUID,
        provider_call_id: str,
        provider_status: str,
    ) -> str:
        """Bind the provider call ID and apply the next legal lifecycle transition."""
        async with self.database.session() as session:
            repository = CallRepository(session)
            call = await repository.get_for_update(call_id)
            if call is None:
                raise UnknownCallError(str(call_id))

            repository.bind_provider_call_id(call, provider_call_id)
            next_status = resolve_call_transition(call.status, provider_status)
            if next_status is not None:
                call.status = next_status
                await EventRepository(session).append(
                    EventCreate(
                        event_type=f"call.{next_status.value.replace('-', '_')}",
                        call_id=call.id,
                        correlation_id=provider_call_id,
                        idempotency_key=(
                            f"call:{call.id}:provider:{provider_call_id}:"
                            f"status:{provider_status.strip().lower()}"
                        ),
                        payload={
                            "status": next_status.value,
                            "provider_status": provider_status,
                            "provider_call_id": provider_call_id,
                        },
                    )
                )

            await session.flush()
            await session.refresh(call)
            return call.status
