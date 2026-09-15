"""Outbound call use case.

This file persists a pending call, asks telephony to dial, and records the result.
"""

from dataclasses import dataclass
from uuid import UUID

from app.agents.repository import AgentRepository
from app.calls.repository import CallRepository
from app.calls.telephony import TelephonyGateway, TelephonyProviderError
from app.db.database import Database


@dataclass(frozen=True)
class InitiatedCall:
    """API-safe result for a provider-accepted outbound call request."""

    id: UUID
    status: str
    provider_call_id: str
    agent_id: UUID | None = None


class UnavailableAgentError(Exception):
    pass


class CallInitiationFailed(Exception):
    def __init__(self, *, call_id: UUID, provider_code: str) -> None:
        super().__init__("Outbound call initiation failed")
        self.call_id = call_id
        self.provider_code = provider_code


class CallService:
    """Use case service for creating outbound calls and issuing Twilio dial commands."""

    def __init__(self, *, database: Database, telephony: TelephonyGateway) -> None:
        self.database = database
        self.telephony = telephony

    async def initiate_call(
        self, to_number: str, agent_id: UUID | None = None
    ) -> InitiatedCall:
        """Persist a pending call, ask Twilio to dial, then record the result."""
        async with self.database.session() as session:
            if (
                agent_id is not None
                and await AgentRepository(session).get(agent_id, selectable=True)
                is None
            ):
                raise UnavailableAgentError(str(agent_id))
            pending_call = await CallRepository(session).create(
                to_phone_number=to_number,
                agent_id=agent_id,
            )
            call_id = pending_call.id

        try:
            provider_call = await self.telephony.create_call(
                call_id=call_id,
                to_number=to_number,
            )
        except TelephonyProviderError as exc:
            async with self.database.session() as session:
                await CallRepository(session).mark_failed(
                    call_id=call_id,
                    failure_code=exc.code,
                )
            raise CallInitiationFailed(
                call_id=call_id,
                provider_code=exc.code,
            ) from exc

        async with self.database.session() as session:
            call = await CallRepository(session).mark_provider_accepted(
                call_id=call_id,
                provider_call_id=provider_call.provider_call_id,
            )

        return InitiatedCall(
            id=call.id,
            status=call.status,
            provider_call_id=provider_call.provider_call_id,
            agent_id=call.active_agent_id,
        )
