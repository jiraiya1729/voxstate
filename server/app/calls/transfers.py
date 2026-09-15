"""Live call transfer use cases.

This file coordinates idempotent transfer records, AI-agent handoff through the active
media session, and human phone handoff through Twilio.
"""

from dataclasses import dataclass
from uuid import UUID

from app.agents.repository import AgentRepository
from app.calls.lifecycle import TERMINAL_STATUSES, CallStatus
from app.calls.models import CallTransfer
from app.calls.repository import CallRepository
from app.calls.telephony import TelephonyGateway, TelephonyProviderError
from app.db.database import Database
from app.voice.runtime import AgentRuntimeFactory
from app.voice.sessions.service import ActiveCallRegistry


class TransferError(Exception):
    pass


class TransferNotFoundError(TransferError):
    pass


class TransferConflictError(TransferError):
    pass


class TransferProviderError(TransferError):
    pass


@dataclass(frozen=True, slots=True)
class TransferResult:
    """API-safe transfer status returned for agent and human handoff commands."""

    id: UUID
    status: str
    kind: str
    failure_code: str | None = None


def _result(transfer: CallTransfer) -> TransferResult:
    """Convert a persisted transfer row into the public service result shape."""
    return TransferResult(
        transfer.id, transfer.status, transfer.kind, transfer.failure_code
    )


class TransferService:
    """Coordinates live agent reconfiguration and Twilio human transfer commands."""

    def __init__(
        self,
        *,
        database: Database,
        registry: ActiveCallRegistry,
        runtime_factory: AgentRuntimeFactory,
        telephony: TelephonyGateway,
    ) -> None:
        self.database = database
        self.registry = registry
        self.runtime_factory = runtime_factory
        self.telephony = telephony

    async def transfer_to_agent(
        self, *, call_id: UUID, target_agent_id: UUID, idempotency_key: str
    ) -> TransferResult:
        """Move an active media session to another agent without losing history."""
        async with self.database.session() as session:
            existing = await CallRepository(session).get_transfer(
                call_id, idempotency_key
            )
            if existing is not None:
                if (
                    existing.kind != "agent"
                    or existing.target_agent_id != target_agent_id
                ):
                    raise TransferConflictError(
                        "idempotency key was used for another transfer"
                    )
                return _result(existing)
        active = await self.registry.get_by_call(call_id)
        if active is None:
            raise TransferNotFoundError("call has no active media session")
        async with self.database.session() as session:
            calls = CallRepository(session)
            existing = await calls.get_transfer(call_id, idempotency_key)
            if existing is not None:
                if (
                    existing.kind != "agent"
                    or existing.target_agent_id != target_agent_id
                ):
                    raise TransferConflictError(
                        "idempotency key was used for another transfer"
                    )
                return _result(existing)
            call = await calls.get_for_update(call_id)
            agent = await AgentRepository(session).get(target_agent_id, selectable=True)
            if call is None or agent is None:
                raise TransferNotFoundError("call or target agent is unavailable")
            transfer = await calls.create_transfer(
                call=call,
                idempotency_key=idempotency_key,
                kind="agent",
                target_agent_id=target_agent_id,
            )
            transfer_id = transfer.id
            runtime = self.runtime_factory.build(agent)

        try:
            await active.transfer_to(target_agent_id, runtime)
        except Exception as exc:
            await self._finish(transfer_id, "failed", "agent_transfer_failed")
            raise TransferConflictError(str(exc)) from exc

        async with self.database.session() as session:
            calls = CallRepository(session)
            call = await calls.get_for_update(call_id)
            if call is None:
                raise TransferNotFoundError(str(call_id))
            await calls.set_active_agent(call, target_agent_id)
            transfer = await session.get(CallTransfer, transfer_id)
            assert transfer is not None
            transfer.status = "completed"
            await session.flush()
            return _result(transfer)

    async def transfer_to_human(
        self, *, call_id: UUID, to_number: str, idempotency_key: str
    ) -> TransferResult:
        """Ask Twilio to hand the live call to a human number and close AI media."""
        async with self.database.session() as session:
            existing = await CallRepository(session).get_transfer(
                call_id, idempotency_key
            )
            if existing is not None:
                if (
                    existing.kind != "human"
                    or existing.target_phone_number != to_number
                ):
                    raise TransferConflictError(
                        "idempotency key was used for another transfer"
                    )
                return _result(existing)
        active = await self.registry.get_by_call(call_id)
        if active is None:
            raise TransferNotFoundError("call has no active media session")
        async with self.database.session() as session:
            calls = CallRepository(session)
            existing = await calls.get_transfer(call_id, idempotency_key)
            if existing is not None:
                if (
                    existing.kind != "human"
                    or existing.target_phone_number != to_number
                ):
                    raise TransferConflictError(
                        "idempotency key was used for another transfer"
                    )
                return _result(existing)
            call = await calls.get_for_update(call_id)
            if call is None or call.provider_call_id is None:
                raise TransferNotFoundError(str(call_id))
            if CallStatus(call.status) in TERMINAL_STATUSES:
                raise TransferConflictError("cannot transfer a terminal call")
            transfer = await calls.create_transfer(
                call=call,
                idempotency_key=idempotency_key,
                kind="human",
                target_phone_number=to_number,
            )
            transfer_id = transfer.id
            provider_call_id = call.provider_call_id
        try:
            await self.telephony.transfer_call(
                provider_call_id=provider_call_id,
                to_number=to_number,
                transfer_id=transfer_id,
            )
        except TelephonyProviderError as exc:
            await self._finish(transfer_id, "failed", exc.code)
            raise TransferProviderError(exc.code) from exc
        result = await self._finish(transfer_id, "accepted", None)
        await self.registry.close(active.stream_sid)
        return result

    async def apply_human_status(
        self, transfer_id: UUID, provider_status: str
    ) -> TransferResult:
        """Normalize Twilio Dial status callbacks onto the transfer record."""
        normalized = {
            "completed": "completed",
            "busy": "failed",
            "no-answer": "failed",
            "failed": "failed",
        }
        if provider_status not in normalized:
            raise TransferConflictError("unsupported transfer status")
        failure = provider_status if normalized[provider_status] == "failed" else None
        return await self._finish(transfer_id, normalized[provider_status], failure)

    async def _finish(
        self, transfer_id: UUID, status: str, failure_code: str | None
    ) -> TransferResult:
        """Mark a transfer terminal or accepted while making repeats idempotent."""
        async with self.database.session() as session:
            transfer = await session.get(CallTransfer, transfer_id)
            if transfer is None:
                raise TransferNotFoundError(str(transfer_id))
            if transfer.status in {"completed", "failed"}:
                return _result(transfer)
            transfer.status = status
            transfer.failure_code = failure_code
            await session.flush()
            return _result(transfer)
