from uuid import UUID

import pytest

from app.agents.schemas import AgentCreate
from app.agents.service import AgentService
from app.calls.outbound import CallInitiationFailed, CallService
from app.calls.telephony import ProviderCall, TelephonyProviderError
from app.cases.schemas import CaseCreate
from app.cases.service import CaseService
from app.db.database import Database
from app.workflows.definition import WorkflowDefinition
from app.workflows.repository import WorkflowRepository
from app.workflows.service import WorkflowRunTerminalError, WorkflowService


class RecordingTelephonyGateway:
    def __init__(self, *, failure_code: str | None = None) -> None:
        self.failure_code = failure_code
        self.requested_numbers: list[str] = []
        self.next_provider_index = 1

    async def create_call(
        self,
        *,
        call_id: UUID,
        to_number: str,
    ) -> ProviderCall:
        self.requested_numbers.append(to_number)
        if self.failure_code is not None:
            raise TelephonyProviderError(self.failure_code)
        provider_id = f"CA{self.next_provider_index:032d}"
        self.next_provider_index += 1
        return ProviderCall(provider_id)


async def create_agent(database: Database) -> UUID:
    agent = await AgentService(database).create(
        AgentCreate(
            name="Workflow Agent",
            system_prompt="Help the caller.",
            bedrock_model_id="test.model",
            cartesia_voice_id="voice-123",
        )
    )
    return agent.id


def definition_for(agent_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "name": "single-call-collection",
            "initial_step_id": "call_customer",
            "steps": [
                {
                    "id": "call_customer",
                    "kind": "call",
                    "agent_id": str(agent_id),
                    "to_number": "+15555550900",
                    "next_step_id": "complete",
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        }
    )


@pytest.mark.asyncio
async def test_workflow_schedules_one_call_and_completes(
    database: Database,
) -> None:
    agent_id = await create_agent(database)
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-1")
    )
    telephony = RecordingTelephonyGateway()
    service = WorkflowService(
        database=database,
        call_service=CallService(database=database, telephony=telephony),
    )
    definition = await service.create_definition(definition_for(agent_id))
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    scheduled = await service.advance_run(run.id)
    duplicate = await service.advance_run(run.id)

    assert scheduled.status == "waiting"
    assert scheduled.scheduled_call_id is not None
    assert scheduled.scheduled_new_activity is True
    assert duplicate.scheduled_call_id == scheduled.scheduled_call_id
    assert duplicate.scheduled_new_activity is False
    assert telephony.requested_numbers == ["+15555550900"]

    completed = await service.complete_call_activity(
        run_id=run.id,
        call_id=scheduled.scheduled_call_id,
    )

    assert completed.status == "completed"
    assert completed.current_step_id == "complete"
    assert completed.completed_step_ids == ["call_customer", "complete"]


@pytest.mark.asyncio
async def test_workflow_resume_after_progress_does_not_repeat_call(
    database: Database,
) -> None:
    agent_id = await create_agent(database)
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-2")
    )
    telephony = RecordingTelephonyGateway()
    call_service = CallService(database=database, telephony=telephony)
    service = WorkflowService(database=database, call_service=call_service)
    definition = await service.create_definition(definition_for(agent_id))
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    scheduled = await service.advance_run(run.id)
    await service.complete_call_activity(
        run_id=run.id,
        call_id=scheduled.scheduled_call_id,
    )

    restarted_service = WorkflowService(database=database, call_service=call_service)

    with pytest.raises(WorkflowRunTerminalError):
        await restarted_service.advance_run(run.id)

    async with database.session() as session:
        stored = await WorkflowRepository(session).get_run(run.id)

    assert stored is not None
    assert stored.status == "completed"
    assert telephony.requested_numbers == ["+15555550900"]


@pytest.mark.asyncio
async def test_workflow_marks_run_failed_when_call_scheduling_fails(
    database: Database,
) -> None:
    agent_id = await create_agent(database)
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-3")
    )
    telephony = RecordingTelephonyGateway(failure_code="provider_rejected")
    service = WorkflowService(
        database=database,
        call_service=CallService(database=database, telephony=telephony),
    )
    definition = await service.create_definition(definition_for(agent_id))
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    with pytest.raises(CallInitiationFailed):
        await service.advance_run(run.id)

    async with database.session() as session:
        stored = await WorkflowRepository(session).get_run(run.id)
        attempt = await WorkflowRepository(session).get_attempt_by_key(
            run_id=run.id,
            idempotency_key=f"workflow-run:{run.id}:step:call_customer:call",
        )

    assert stored is not None
    assert stored.status == "failed"
    assert stored.failure_code == "provider_rejected"
    assert attempt is not None
    assert attempt.status == "failed"
    assert attempt.failure_code == "provider_rejected"
