"""Database repository for call and transfer rows.

This file contains SQLAlchemy queries for calls, provider IDs, locks, and transfers.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.lifecycle import CallStatus, ProviderCallMismatchError
from app.calls.models import Call, CallTransfer


class CallRepository:
    def __init__(self, session: AsyncSession) -> None:
        # Repositories reuse the service-owned SQLAlchemy session/transaction.
        self.session = session

    async def create(
        self,
        *,
        to_phone_number: str,
        agent_id: UUID | None = None,
        case_id: UUID | None = None,
        from_phone_number: str | None = None,
        direction: str = "outbound",
        provider_call_id: str | None = None,
    ) -> Call:
        # Insert a new call row and return the refreshed SQLAlchemy model.
        call = Call(
            to_phone_number=to_phone_number,
            from_phone_number=from_phone_number,
            direction=direction,
            initial_agent_id=agent_id,
            active_agent_id=agent_id,
            case_id=case_id,
            provider_call_id=provider_call_id,
        )
        self.session.add(call)
        await self.session.flush()
        await self.session.refresh(call)
        return call

    async def get_by_id(self, call_id: UUID | str) -> Call | None:
        # Find a call by internal UUID; invalid string IDs are treated as not found.
        if isinstance(call_id, str):
            try:
                call_id = UUID(call_id)
            except ValueError:
                return None
        return await self.session.get(Call, call_id)

    async def get_for_update(self, call_id: UUID) -> Call | None:
        # Lock the call row so concurrent updates cannot race this transaction.
        result = await self.session.execute(
            select(Call).where(Call.id == call_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_provider_call_id(self, provider_call_id: str) -> Call | None:
        # Find a call by Twilio/provider call SID for incoming provider callbacks.
        result = await self.session.execute(
            select(Call).where(Call.provider_call_id == provider_call_id)
        )
        return result.scalar_one_or_none()

    async def set_active_agent(self, call: Call, agent_id: UUID) -> None:
        # Switch the call's currently active agent after a validated agent transfer.
        call.active_agent_id = agent_id
        await self.session.flush()

    async def create_transfer(
        self,
        *,
        call: Call,
        idempotency_key: str,
        kind: str,
        target_agent_id: UUID | None = None,
        target_phone_number: str | None = None,
    ) -> CallTransfer:
        # Record a transfer; call_id + idempotency_key enforces uniqueness.
        transfer = CallTransfer(
            call_id=call.id,
            idempotency_key=idempotency_key,
            kind=kind,
            source_agent_id=call.active_agent_id,
            target_agent_id=target_agent_id,
            target_phone_number=target_phone_number,
            status="pending",
        )
        self.session.add(transfer)
        await self.session.flush()
        return transfer

    async def get_transfer(
        self, call_id: UUID, idempotency_key: str
    ) -> CallTransfer | None:
        # Return an existing transfer attempt for idempotent transfer retries.
        result = await self.session.execute(
            select(CallTransfer).where(
                CallTransfer.call_id == call_id,
                CallTransfer.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def mark_provider_accepted(
        self,
        *,
        call_id: UUID,
        provider_call_id: str,
    ) -> Call:
        # Bind Twilio's call SID and move pending calls to queued.
        call = await self._require_for_update(call_id)
        self.bind_provider_call_id(call, provider_call_id)

        if call.status == CallStatus.PENDING:
            call.status = CallStatus.QUEUED

        call.failure_code = None
        await self.session.flush()
        await self.session.refresh(call)
        return call

    async def mark_failed(self, *, call_id: UUID, failure_code: str) -> Call:
        # Persist provider failure so failed calls are not reported as success.
        call = await self._require_for_update(call_id)
        call.status = CallStatus.FAILED
        call.failure_code = failure_code
        await self.session.flush()
        await self.session.refresh(call)
        return call

    async def _require_for_update(self, call_id: UUID) -> Call:
        # Lock and require a call row before applying state-changing updates.
        call = await self.get_for_update(call_id)
        if call is None:
            raise LookupError(f"Call {call_id} does not exist")
        return call

    @staticmethod
    def bind_provider_call_id(call: Call, provider_call_id: str) -> None:
        # Attach the provider call ID once; reject mismatches from wrong callbacks.
        if (
            call.provider_call_id is not None
            and call.provider_call_id != provider_call_id
        ):
            raise ProviderCallMismatchError(provider_call_id)

        call.provider_call_id = provider_call_id
