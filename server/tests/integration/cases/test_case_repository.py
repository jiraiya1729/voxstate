from datetime import UTC, datetime

import pytest

from app.calls.repository import CallRepository
from app.cases.errors import CaseConcurrencyError
from app.cases.repository import CaseRepository
from app.cases.schemas import CaseCreate, CaseStateUpdate
from app.db.database import Database


@pytest.mark.asyncio
async def test_case_repository_creates_and_reads_case(database: Database) -> None:
    async with database.session() as session:
        created = await CaseRepository(session).create(
            CaseCreate(
                customer_reference_id="customer-123",
                business_state="new_lead",
                customer_state={"timezone": "UTC"},
            )
        )

    async with database.session() as session:
        stored = await CaseRepository(session).get_by_id(created.id)

    assert stored is not None
    assert stored.customer_reference_id == "customer-123"
    assert stored.status == "open"
    assert stored.business_state == "new_lead"
    assert stored.customer_state == {"timezone": "UTC"}
    assert stored.version == 1


@pytest.mark.asyncio
async def test_case_state_update_persists_across_sessions(database: Database) -> None:
    callback_at = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    async with database.session() as session:
        case = await CaseRepository(session).create(
            CaseCreate(customer_reference_id="customer-124")
        )

    async with database.session() as session:
        updated = await CaseRepository(session).update_state(
            case_id=case.id,
            expected_version=1,
            update_payload=CaseStateUpdate(
                status="waiting",
                business_state="callback_scheduled",
                attempt_count=2,
                last_outcome={
                    "kind": "callback_requested",
                    "callback_at": callback_at,
                },
                customer_state={"timezone": "UTC", "balance_due": 42},
            ),
        )

    assert updated.version == 2

    async with database.session() as session:
        stored = await CaseRepository(session).get_by_id(case.id)

    assert stored is not None
    assert stored.status == "waiting"
    assert stored.business_state == "callback_scheduled"
    assert stored.attempt_count == 2
    assert stored.last_outcome is not None
    assert stored.last_outcome["kind"] == "callback_requested"
    assert stored.callback_at == callback_at
    assert stored.customer_state == {"timezone": "UTC", "balance_due": 42}


@pytest.mark.asyncio
async def test_case_state_update_rejects_stale_version(database: Database) -> None:
    async with database.session() as session:
        case = await CaseRepository(session).create(
            CaseCreate(customer_reference_id="customer-125")
        )
        await CaseRepository(session).update_state(
            case_id=case.id,
            expected_version=1,
            update_payload=CaseStateUpdate(attempt_count=1),
        )

    async with database.session() as session:
        with pytest.raises(CaseConcurrencyError):
            await CaseRepository(session).update_state(
                case_id=case.id,
                expected_version=1,
                update_payload=CaseStateUpdate(attempt_count=2),
            )


@pytest.mark.asyncio
async def test_case_can_own_multiple_calls(database: Database) -> None:
    async with database.session() as session:
        case = await CaseRepository(session).create(
            CaseCreate(customer_reference_id="customer-126")
        )
        calls = [
            await CallRepository(session).create(
                to_phone_number=f"+1555555020{index}",
                case_id=case.id,
            )
            for index in range(2)
        ]

    async with database.session() as session:
        stored_calls = [
            await CallRepository(session).get_by_id(call.id) for call in calls
        ]

    assert [call.case_id for call in stored_calls if call is not None] == [
        case.id,
        case.id,
    ]
