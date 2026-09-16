"""Application service for durable customer cases."""

from uuid import UUID

from app.calls.repository import CallRepository
from app.cases.errors import CaseAttachmentError, CaseNotFoundError
from app.cases.repository import CaseRepository
from app.cases.schemas import CaseCreate, CaseStateUpdate
from app.db.database import Database


class CaseService:
    """Coordinates case creation, call attachment, and persistent state updates."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_case(self, payload: CaseCreate):
        async with self.database.session() as session:
            return await CaseRepository(session).create(payload)

    async def attach_call(self, *, case_id: UUID, call_id: UUID):
        async with self.database.session() as session:
            case_repository = CaseRepository(session)
            call_repository = CallRepository(session)
            case = await case_repository.get_by_id(case_id)
            if case is None:
                raise CaseNotFoundError(str(case_id))
            call = await call_repository.get_by_id(call_id)
            if call is None:
                raise LookupError(f"Call {call_id} does not exist")
            if call.case_id is not None and call.case_id != case.id:
                raise CaseAttachmentError("call is already attached to another case")
            return await case_repository.attach_call(case=case, call=call)

    async def update_state(
        self,
        *,
        case_id: UUID,
        update_payload: CaseStateUpdate,
        expected_version: int,
    ):
        async with self.database.session() as session:
            return await CaseRepository(session).update_state(
                case_id=case_id,
                update_payload=update_payload,
                expected_version=expected_version,
            )
