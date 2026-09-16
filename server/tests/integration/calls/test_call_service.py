from uuid import UUID

import pytest

from app.calls.outbound import CallInitiationFailed, CallService
from app.calls.repository import CallRepository
from app.calls.telephony import ProviderCall, TelephonyProviderError
from app.db.database import Database
from app.events.repository import EventRepository


class RecordingTelephonyGateway:
    def __init__(self, *, failure_code: str | None = None) -> None:
        self.failure_code = failure_code
        self.requested_numbers: list[str] = []

    async def create_call(
        self,
        *,
        call_id: UUID,
        to_number: str,
    ) -> ProviderCall:
        self.requested_numbers.append(to_number)

        if self.failure_code is not None:
            raise TelephonyProviderError(self.failure_code)

        return ProviderCall("CA00000000000000000000000000000001")


@pytest.mark.asyncio
async def test_successful_provider_request_marks_call_queued(
    database: Database,
) -> None:
    telephony = RecordingTelephonyGateway()
    service = CallService(database=database, telephony=telephony)

    result = await service.initiate_call("+15555550110")

    assert telephony.requested_numbers == ["+15555550110"]
    assert result.status == "queued"
    assert result.provider_call_id == "CA00000000000000000000000000000001"

    async with database.session() as session:
        stored = await CallRepository(session).get_by_id(result.id)
        events = await EventRepository(session).list_for_call(result.id)

    assert stored is not None
    assert stored.status == "queued"
    assert stored.provider_call_id == result.provider_call_id
    assert stored.failure_code is None
    assert [event.event_type for event in events] == ["call.requested", "call.queued"]
    assert [event.sequence for event in events] == [1, 2]


@pytest.mark.asyncio
async def test_provider_failure_is_persisted_and_not_reported_as_success(
    database: Database,
) -> None:
    telephony = RecordingTelephonyGateway(failure_code="21211")
    service = CallService(database=database, telephony=telephony)

    with pytest.raises(CallInitiationFailed) as captured:
        await service.initiate_call("+15555550111")

    async with database.session() as session:
        stored = await CallRepository(session).get_by_id(captured.value.call_id)
        events = await EventRepository(session).list_for_call(captured.value.call_id)

    assert stored is not None
    assert stored.status == "failed"
    assert stored.provider_call_id is None
    assert stored.failure_code == "21211"
    assert [event.event_type for event in events] == ["call.requested", "call.failed"]
