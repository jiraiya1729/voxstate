import pytest

from app.calls.repository import CallRepository
from app.cases.errors import CaseAttachmentError, CaseNotFoundError
from app.cases.schemas import CaseCreate
from app.cases.service import CaseService
from app.db.database import Database


@pytest.mark.asyncio
async def test_attach_call_to_case_is_idempotent(database: Database) -> None:
    service = CaseService(database)
    case = await service.create_case(CaseCreate(customer_reference_id="customer-200"))
    async with database.session() as session:
        call = await CallRepository(session).create(to_phone_number="+15555550300")

    first = await service.attach_call(case_id=case.id, call_id=call.id)
    second = await service.attach_call(case_id=case.id, call_id=call.id)

    assert first.case_id == case.id
    assert second.case_id == case.id


@pytest.mark.asyncio
async def test_attach_call_rejects_unknown_case(database: Database) -> None:
    service = CaseService(database)
    existing_case = await service.create_case(
        CaseCreate(customer_reference_id="customer-201")
    )
    async with database.session() as session:
        call = await CallRepository(session).create(to_phone_number="+15555550301")

    with pytest.raises(CaseNotFoundError):
        await service.attach_call(case_id=call.id, call_id=call.id)

    attached = await service.attach_call(case_id=existing_case.id, call_id=call.id)
    assert attached.case_id == existing_case.id


@pytest.mark.asyncio
async def test_attach_call_rejects_double_attachment(database: Database) -> None:
    service = CaseService(database)
    first_case = await service.create_case(
        CaseCreate(customer_reference_id="customer-202")
    )
    second_case = await service.create_case(
        CaseCreate(customer_reference_id="customer-203")
    )
    async with database.session() as session:
        call = await CallRepository(session).create(to_phone_number="+15555550302")

    await service.attach_call(case_id=first_case.id, call_id=call.id)

    with pytest.raises(CaseAttachmentError):
        await service.attach_call(case_id=second_case.id, call_id=call.id)
