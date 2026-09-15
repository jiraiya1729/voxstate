"""Inbound call use case.

This file deduplicates Twilio inbound calls, routes them, and persists them.
"""

from dataclasses import dataclass
from uuid import UUID

from app.agents.routing import RoutingContext, RoutingService
from app.calls.lifecycle import CallStatus, ProviderCallMismatchError
from app.calls.repository import CallRepository
from app.db.database import Database


@dataclass(frozen=True, slots=True)
class AcceptedInboundCall:
    """Internal result containing the call and selected agent for Twilio media TwiML."""

    id: UUID
    agent_id: UUID


class InboundCallService:
    """Use case service for accepting signed inbound Twilio calls and routing agents."""

    def __init__(self, *, database: Database, routing: RoutingService) -> None:
        self.database = database
        self.routing = routing

    async def accept(
        self,
        *,
        provider_call_id: str,
        from_number: str,
        to_number: str,
        language: str | None = None,
        category: str | None = None,
    ) -> AcceptedInboundCall:
        """Resolve an inbound destination to an agent and persist the inbound call."""
        async with self.database.session() as session:
            repository = CallRepository(session)
            existing = await repository.get_by_provider_call_id(provider_call_id)
            if existing is not None:
                if (
                    existing.to_phone_number != to_number
                    or existing.active_agent_id is None
                ):
                    raise ProviderCallMismatchError(provider_call_id)
                return AcceptedInboundCall(existing.id, existing.active_agent_id)
        decision = await self.routing.resolve(
            RoutingContext(
                called_number=to_number, language=language, category=category
            )
        )
        async with self.database.session() as session:
            repository = CallRepository(session)
            call = await repository.create(
                to_phone_number=to_number,
                from_phone_number=from_number,
                direction="inbound",
                agent_id=decision.agent.id,
                provider_call_id=provider_call_id,
            )
            call.status = CallStatus.QUEUED
            await session.flush()
            return AcceptedInboundCall(call.id, decision.agent.id)
