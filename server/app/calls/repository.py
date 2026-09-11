from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.lifecycle import CallStatus, ProviderCallMismatchError
from app.calls.models import Call


class CallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, to_phone_number: str) -> Call:
        call = Call(to_phone_number=to_phone_number)
        self.session.add(call)
        await self.session.flush()
        await self.session.refresh(call)
        return call

    async def get_by_id(self, call_id: UUID | str) -> Call | None:
        if isinstance(call_id, str):
            try:
                call_id = UUID(call_id)
            except ValueError:
                return None
        return await self.session.get(Call, call_id)

    async def get_for_update(self, call_id: UUID) -> Call | None:
        result = await self.session.execute(
            select(Call).where(Call.id == call_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def mark_provider_accepted(
        self,
        *,
        call_id: UUID,
        provider_call_id: str,
    ) -> Call:
        call = await self._require_for_update(call_id)
        self.bind_provider_call_id(call, provider_call_id)

        if call.status == CallStatus.PENDING:
            call.status = CallStatus.QUEUED

        call.failure_code = None
        await self.session.flush()
        await self.session.refresh(call)
        return call

    async def mark_failed(self, *, call_id: UUID, failure_code: str) -> Call:
        call = await self._require_for_update(call_id)
        call.status = CallStatus.FAILED
        call.failure_code = failure_code
        await self.session.flush()
        await self.session.refresh(call)
        return call

    async def _require_for_update(self, call_id: UUID) -> Call:
        call = await self.get_for_update(call_id)
        if call is None:
            raise LookupError(f"Call {call_id} does not exist")
        return call

    @staticmethod
    def bind_provider_call_id(call: Call, provider_call_id: str) -> None:
        if (
            call.provider_call_id is not None
            and call.provider_call_id != provider_call_id
        ):
            raise ProviderCallMismatchError(provider_call_id)

        call.provider_call_id = provider_call_id
