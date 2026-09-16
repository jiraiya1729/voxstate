"""Database repository for durable cases."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import Call
from app.cases.errors import CaseConcurrencyError, CaseNotFoundError
from app.cases.models import Case
from app.cases.schemas import CaseCreate, CaseStateUpdate


class CaseRepository:
    """Persistence boundary for case records and call attachment."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: CaseCreate) -> Case:
        case = Case(
            customer_reference_id=payload.customer_reference_id,
            business_state=payload.business_state,
            customer_state=payload.customer_state,
        )
        self.session.add(case)
        await self.session.flush()
        await self.session.refresh(case)
        return case

    async def get_by_id(self, case_id: UUID | str) -> Case | None:
        if isinstance(case_id, str):
            try:
                case_id = UUID(case_id)
            except ValueError:
                return None
        return await self.session.get(Case, case_id)

    async def get_for_update(self, case_id: UUID) -> Case | None:
        result = await self.session.execute(
            select(Case).where(Case.id == case_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def attach_call(self, *, case: Case, call: Call) -> Call:
        call.case_id = case.id
        await self.session.flush()
        await self.session.refresh(call)
        return call

    async def update_state(
        self,
        *,
        case_id: UUID,
        update_payload: CaseStateUpdate,
        expected_version: int,
    ) -> Case:
        values: dict[str, object] = {"version": expected_version + 1}
        if update_payload.status is not None:
            values["status"] = update_payload.status.value
        if update_payload.business_state is not None:
            values["business_state"] = update_payload.business_state
        if update_payload.attempt_count is not None:
            values["attempt_count"] = update_payload.attempt_count
        if update_payload.last_outcome is not None:
            values["last_outcome"] = update_payload.last_outcome.model_dump(mode="json")
        if update_payload.callback_at is not None:
            values["callback_at"] = update_payload.callback_at
        if update_payload.customer_state is not None:
            values["customer_state"] = update_payload.customer_state

        result = await self.session.execute(
            update(Case)
            .where(Case.id == case_id, Case.version == expected_version)
            .values(**values)
            .returning(Case)
        )
        case = result.scalar_one_or_none()
        if case is None:
            existing = await self.get_by_id(case_id)
            if existing is None:
                raise CaseNotFoundError(str(case_id))
            raise CaseConcurrencyError(str(case_id))
        await self.session.flush()
        await self.session.refresh(case)
        return case
