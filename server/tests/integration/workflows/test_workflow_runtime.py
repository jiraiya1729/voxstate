from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.agents.schemas import AgentCreate
from app.agents.service import AgentService
from app.calls.outbound import CallInitiationFailed, CallService
from app.calls.outcomes import CallOutcome
from app.calls.telephony import ProviderCall, TelephonyProviderError
from app.cases.schemas import CaseCreate
from app.cases.service import CaseService
from app.db.database import Database
from app.workflows.definition import WorkflowDefinition
from app.workflows.models import WorkflowTimer
from app.workflows.repository import WorkflowRepository
from app.workflows.service import (
    ExternalEventAuthenticationError,
    WorkflowRunTerminalError,
    WorkflowService,
)


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


BASE_TIME = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


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


def wait_definition_for(agent_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "name": "wait-then-call",
            "initial_step_id": "wait_before_call",
            "steps": [
                {
                    "id": "wait_before_call",
                    "kind": "wait",
                    "delay_seconds": 300,
                    "next_step_id": "call_customer",
                },
                {
                    "id": "call_customer",
                    "kind": "call",
                    "agent_id": str(agent_id),
                    "to_number": "+15555550901",
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


def retry_definition_for(agent_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "name": "retry-call",
            "initial_step_id": "call_customer",
            "steps": [
                {
                    "id": "call_customer",
                    "kind": "call",
                    "agent_id": str(agent_id),
                    "to_number": "+15555550902",
                    "next_step_id": "complete",
                    "on_no_answer_step_id": "failed_terminal",
                    "retry_policy": {
                        "max_attempts": 2,
                        "delay_seconds": 120,
                        "backoff": "fixed",
                        "retry_on": ["no-answer"],
                    },
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
                {
                    "id": "failed_terminal",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        }
    )


def callback_definition_for(agent_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "name": "callback-call",
            "initial_step_id": "call_customer",
            "steps": [
                {
                    "id": "call_customer",
                    "kind": "call",
                    "agent_id": str(agent_id),
                    "to_number": "+15555550903",
                    "next_step_id": "complete",
                    "callback_step_id": "call_customer",
                    "retry_policy": {"max_attempts": 1},
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
            ],
        }
    )


def event_definition_for() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "name": "payment-event-workflow",
            "initial_step_id": "wait_for_payment",
            "steps": [
                {
                    "id": "wait_for_payment",
                    "kind": "wait_for_event",
                    "event_type": "payment.received",
                    "correlation_key": "case:event-123",
                    "on_event_step_id": "complete",
                    "timeout_seconds": 600,
                    "on_timeout_step_id": "timeout_complete",
                },
                {
                    "id": "complete",
                    "kind": "complete",
                    "result": "succeeded",
                },
                {
                    "id": "timeout_complete",
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
            idempotency_key=f"workflow-run:{run.id}:step:call_customer:call:1",
        )

    assert stored is not None
    assert stored.status == "failed"
    assert stored.failure_code == "provider_rejected"
    assert attempt is not None
    assert attempt.status == "failed"
    assert attempt.failure_code == "provider_rejected"


@pytest.mark.asyncio
async def test_durable_wait_wakes_once_after_restart(database: Database) -> None:
    agent_id = await create_agent(database)
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-4")
    )
    telephony = RecordingTelephonyGateway()
    call_service = CallService(database=database, telephony=telephony)
    service = WorkflowService(database=database, call_service=call_service)
    definition = await service.create_definition(wait_definition_for(agent_id))
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    waiting = await service.advance_run(run.id, now=BASE_TIME)
    duplicate_wait = await service.advance_run(run.id, now=BASE_TIME)

    assert waiting.status == "waiting"
    assert waiting.scheduled_timer_id == duplicate_wait.scheduled_timer_id
    assert telephony.requested_numbers == []

    restarted_service = WorkflowService(database=database, call_service=call_service)
    early_results = await restarted_service.fire_due_timers(
        now=BASE_TIME + timedelta(seconds=299)
    )
    due_results = await restarted_service.fire_due_timers(
        now=BASE_TIME + timedelta(seconds=300)
    )
    duplicate_due_results = await restarted_service.fire_due_timers(
        now=BASE_TIME + timedelta(seconds=300)
    )

    assert early_results == []
    assert len(due_results) == 1
    assert due_results[0].scheduled_call_id is not None
    assert duplicate_due_results == []
    assert telephony.requested_numbers == ["+15555550901"]


@pytest.mark.asyncio
async def test_cancellation_suppresses_pending_wait_timer(database: Database) -> None:
    agent_id = await create_agent(database)
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-5")
    )
    telephony = RecordingTelephonyGateway()
    service = WorkflowService(
        database=database,
        call_service=CallService(database=database, telephony=telephony),
    )
    definition = await service.create_definition(wait_definition_for(agent_id))
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    await service.advance_run(run.id, now=BASE_TIME)
    cancelled = await service.cancel_run(run.id)
    results = await service.fire_due_timers(now=BASE_TIME + timedelta(hours=1))

    assert cancelled.status == "cancelled"
    assert results == []
    assert telephony.requested_numbers == []


@pytest.mark.asyncio
async def test_retry_policy_schedules_next_attempt_once(database: Database) -> None:
    agent_id = await create_agent(database)
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-6")
    )
    telephony = RecordingTelephonyGateway()
    call_service = CallService(database=database, telephony=telephony)
    service = WorkflowService(database=database, call_service=call_service)
    definition = await service.create_definition(retry_definition_for(agent_id))
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    first = await service.advance_run(run.id, now=BASE_TIME)
    waiting = await service.complete_call_activity(
        run_id=run.id,
        call_id=first.scheduled_call_id,
        call_status="no-answer",
        now=BASE_TIME,
    )
    early = await service.fire_due_timers(now=BASE_TIME + timedelta(seconds=119))
    due = await service.fire_due_timers(now=BASE_TIME + timedelta(seconds=120))
    duplicate_due = await service.fire_due_timers(
        now=BASE_TIME + timedelta(seconds=120)
    )

    assert waiting.status == "waiting"
    assert early == []
    assert len(due) == 1
    assert due[0].scheduled_new_activity is True
    assert duplicate_due == []
    assert telephony.requested_numbers == ["+15555550902", "+15555550902"]


@pytest.mark.asyncio
async def test_terminal_call_outcome_branches_after_max_attempts(
    database: Database,
) -> None:
    agent_id = await create_agent(database)
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-7")
    )
    telephony = RecordingTelephonyGateway()
    service = WorkflowService(
        database=database,
        call_service=CallService(database=database, telephony=telephony),
    )
    definition = await service.create_definition(retry_definition_for(agent_id))
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    first = await service.advance_run(run.id, now=BASE_TIME)
    await service.complete_call_activity(
        run_id=run.id,
        call_id=first.scheduled_call_id,
        call_status="no-answer",
        now=BASE_TIME,
    )
    retry = (await service.fire_due_timers(now=BASE_TIME + timedelta(seconds=120)))[0]
    branched = await service.complete_call_activity(
        run_id=run.id,
        call_id=retry.scheduled_call_id,
        call_status="no-answer",
        now=BASE_TIME + timedelta(seconds=120),
    )
    duplicate = await service.complete_call_activity(
        run_id=run.id,
        call_id=retry.scheduled_call_id,
        call_status="no-answer",
        now=BASE_TIME + timedelta(seconds=120),
    )

    assert branched.status == "completed"
    assert branched.current_step_id == "failed_terminal"
    assert duplicate.id == branched.id
    assert telephony.requested_numbers == ["+15555550902", "+15555550902"]


@pytest.mark.asyncio
async def test_callback_request_wakes_and_initiates_one_next_call(
    database: Database,
) -> None:
    agent_id = await create_agent(database)
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-8")
    )
    telephony = RecordingTelephonyGateway()
    call_service = CallService(database=database, telephony=telephony)
    service = WorkflowService(database=database, call_service=call_service)
    definition = await service.create_definition(callback_definition_for(agent_id))
    run = await service.start_run(definition_id=definition.id, case_id=case.id)
    callback_at = BASE_TIME + timedelta(hours=2)

    first = await service.advance_run(run.id, now=BASE_TIME)
    waiting = await service.complete_call_activity(
        run_id=run.id,
        call_id=first.scheduled_call_id,
        outcome=CallOutcome(
            kind="callback_requested",
            callback_at=callback_at,
            summary="Caller asked for a later call.",
        ),
        now=BASE_TIME,
    )

    assert waiting.status == "waiting"

    restarted_service = WorkflowService(database=database, call_service=call_service)
    early = await restarted_service.fire_due_timers(
        now=callback_at - timedelta(seconds=1)
    )
    due = await restarted_service.fire_due_timers(now=callback_at)
    duplicate_due = await restarted_service.fire_due_timers(now=callback_at)

    async with database.session() as session:
        timers = (
            await session.execute(
                WorkflowTimer.__table__.select().where(
                    WorkflowTimer.run_id == run.id,
                    WorkflowTimer.kind == "callback",
                )
            )
        ).all()

    assert early == []
    assert len(due) == 1
    assert due[0].scheduled_new_activity is True
    assert duplicate_due == []
    assert len(timers) == 1
    assert telephony.requested_numbers == ["+15555550903", "+15555550903"]


@pytest.mark.asyncio
async def test_external_event_resumes_matching_wait_once(database: Database) -> None:
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-9")
    )
    service = WorkflowService(
        database=database,
        call_service=CallService(
            database=database,
            telephony=RecordingTelephonyGateway(),
        ),
    )
    definition = await service.create_definition(event_definition_for())
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    waiting = await service.advance_run(run.id, now=BASE_TIME)
    matched = await service.ingest_external_event(
        event_type="payment.received",
        correlation_key="case:event-123",
        idempotency_key="evt-1",
        payload={"amount": 42},
        provided_secret="secret",
        expected_secret="secret",
        now=BASE_TIME + timedelta(seconds=10),
    )
    duplicate = await service.ingest_external_event(
        event_type="payment.received",
        correlation_key="case:event-123",
        idempotency_key="evt-1",
        payload={"amount": 42},
        provided_secret="secret",
        expected_secret="secret",
        now=BASE_TIME + timedelta(seconds=10),
    )
    timeout_results = await service.fire_due_timers(
        now=BASE_TIME + timedelta(seconds=600)
    )

    async with database.session() as session:
        stored = await WorkflowRepository(session).get_run(run.id)

    assert waiting.status == "waiting"
    assert matched.matched_run_id == run.id
    assert duplicate.was_duplicate is True
    assert duplicate.matched_run_id == run.id
    assert timeout_results == []
    assert stored is not None
    assert stored.status == "completed"
    assert stored.current_step_id == "complete"


@pytest.mark.asyncio
async def test_external_event_rejects_invalid_secret(database: Database) -> None:
    service = WorkflowService(
        database=database,
        call_service=CallService(
            database=database,
            telephony=RecordingTelephonyGateway(),
        ),
    )

    with pytest.raises(ExternalEventAuthenticationError):
        await service.ingest_external_event(
            event_type="payment.received",
            correlation_key="case:event-123",
            idempotency_key="evt-bad-secret",
            provided_secret="wrong",
            expected_secret="secret",
        )


@pytest.mark.asyncio
async def test_external_event_timeout_wins_and_late_event_is_noop(
    database: Database,
) -> None:
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-10")
    )
    service = WorkflowService(
        database=database,
        call_service=CallService(
            database=database,
            telephony=RecordingTelephonyGateway(),
        ),
    )
    definition = await service.create_definition(event_definition_for())
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    await service.advance_run(run.id, now=BASE_TIME)
    timeout_results = await service.fire_due_timers(
        now=BASE_TIME + timedelta(seconds=600)
    )
    late_event = await service.ingest_external_event(
        event_type="payment.received",
        correlation_key="case:event-123",
        idempotency_key="evt-late",
        payload={"amount": 42},
        now=BASE_TIME + timedelta(seconds=601),
    )

    async with database.session() as session:
        stored = await WorkflowRepository(session).get_run(run.id)

    assert len(timeout_results) == 1
    assert timeout_results[0].status == "completed"
    assert late_event.matched_run_id is None
    assert stored is not None
    assert stored.status == "completed"
    assert stored.current_step_id == "timeout_complete"


@pytest.mark.asyncio
async def test_cancelled_event_wait_suppresses_event_and_timeout(
    database: Database,
) -> None:
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-11")
    )
    service = WorkflowService(
        database=database,
        call_service=CallService(
            database=database,
            telephony=RecordingTelephonyGateway(),
        ),
    )
    definition = await service.create_definition(event_definition_for())
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    await service.advance_run(run.id, now=BASE_TIME)
    cancelled = await service.cancel_run(run.id)
    event_result = await service.ingest_external_event(
        event_type="payment.received",
        correlation_key="case:event-123",
        idempotency_key="evt-after-cancel",
        now=BASE_TIME + timedelta(seconds=1),
    )
    timeout_results = await service.fire_due_timers(
        now=BASE_TIME + timedelta(seconds=600)
    )

    assert cancelled.status == "cancelled"
    assert event_result.matched_run_id is None
    assert timeout_results == []


@pytest.mark.asyncio
async def test_pause_blocks_event_and_timeout_until_resume(database: Database) -> None:
    case = await CaseService(database).create_case(
        CaseCreate(customer_reference_id="customer-workflow-12")
    )
    service = WorkflowService(
        database=database,
        call_service=CallService(
            database=database,
            telephony=RecordingTelephonyGateway(),
        ),
    )
    definition = await service.create_definition(event_definition_for())
    run = await service.start_run(definition_id=definition.id, case_id=case.id)

    await service.advance_run(run.id, now=BASE_TIME)
    paused = await service.pause_run(run.id)
    event_while_paused = await service.ingest_external_event(
        event_type="payment.received",
        correlation_key="case:event-123",
        idempotency_key="evt-paused",
        now=BASE_TIME + timedelta(seconds=1),
    )
    timeout_while_paused = await service.fire_due_timers(
        now=BASE_TIME + timedelta(seconds=600)
    )
    resumed = await service.resume_run(run.id, now=BASE_TIME + timedelta(seconds=601))
    timeout_after_resume = await service.fire_due_timers(
        now=BASE_TIME + timedelta(seconds=601)
    )

    assert paused.status == "paused"
    assert event_while_paused.matched_run_id is None
    assert timeout_while_paused == []
    assert resumed.status == "waiting"
    assert len(timeout_after_resume) == 1
    assert timeout_after_resume[0].status == "completed"
