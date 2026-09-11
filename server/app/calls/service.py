from dataclasses import dataclass
from uuid import UUID

from app.calls.lifecycle import (
    UnknownCallError,
    resolve_call_transition,
)
from app.calls.repository import CallRepository
from app.calls.telephony import TelephonyGateway, TelephonyProviderError
from app.db.database import Database


@dataclass(frozen=True)
class InitiatedCall:
    id: UUID
    status: str
    provider_call_id: str


class CallInitiationFailed(Exception):
    def __init__(self, *, call_id: UUID, provider_code: str) -> None:
        super().__init__("Outbound call initiation failed")
        self.call_id = call_id
        self.provider_code = provider_code


class CallService:
    def __init__(self, *, database: Database, telephony: TelephonyGateway) -> None:
        self.database = database
        self.telephony = telephony

    async def initiate_call(self, to_number: str) -> InitiatedCall:
        async with self.database.session() as session:
            pending_call = await CallRepository(session).create(
                to_phone_number=to_number
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
        )


class CallLifecycleService:
    def __init__(self, *, database: Database) -> None:
        self.database = database

    async def apply_status_callback(
        self,
        *,
        call_id: UUID,
        provider_call_id: str,
        provider_status: str,
    ) -> str:
        async with self.database.session() as session:
            repository = CallRepository(session)
            call = await repository.get_for_update(call_id)
            if call is None:
                raise UnknownCallError(str(call_id))

            repository.bind_provider_call_id(call, provider_call_id)
            next_status = resolve_call_transition(call.status, provider_status)
            if next_status is not None:
                call.status = next_status

            await session.flush()
            await session.refresh(call)
            return call.status
