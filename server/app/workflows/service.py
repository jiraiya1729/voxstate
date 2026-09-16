"""Application service for the first durable workflow runtime."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.calls.lifecycle import CallStatus
from app.calls.outbound import CallInitiationFailed, CallService, UnavailableAgentError
from app.calls.outcomes import CallOutcome, CallOutcomeKind
from app.cases.errors import CaseNotFoundError
from app.cases.repository import CaseRepository
from app.db.database import Database
from app.workflows.definition import (
    CallActivityDefinition,
    WaitForEventStepDefinition,
    WaitStepDefinition,
    WorkflowDefinition,
    WorkflowStep,
)
from app.workflows.models import WorkflowDefinitionRecord, WorkflowRun
from app.workflows.repository import WorkflowRepository
from app.workflows.state import TERMINAL_WORKFLOW_STATUSES, WorkflowRunStatus


class WorkflowDefinitionNotFoundError(LookupError):
    """Raised when a workflow definition ID does not exist."""


class WorkflowRunNotFoundError(LookupError):
    """Raised when a workflow run ID does not exist."""


class WorkflowRunTerminalError(ValueError):
    """Raised when trying to advance a terminal workflow run."""


class WorkflowActivityMismatchError(ValueError):
    """Raised when an activity completion does not match the waiting run."""


class ExternalEventAuthenticationError(PermissionError):
    """Raised when external event ingestion is not authenticated."""


class ExternalEventValidationError(ValueError):
    """Raised when an external event payload is malformed."""


@dataclass(frozen=True)
class WorkflowAdvanceResult:
    """Compact result returned after advancing one workflow run."""

    run_id: UUID
    status: WorkflowRunStatus
    current_step_id: str
    scheduled_call_id: UUID | None = None
    scheduled_new_activity: bool = False
    scheduled_timer_id: UUID | None = None


@dataclass(frozen=True)
class ExternalEventIngestResult:
    """Result of idempotent external event ingestion."""

    event_id: UUID
    matched_run_id: UUID | None
    was_duplicate: bool = False


class WorkflowService:
    """Coordinates durable workflow definitions, runs, and call activities."""

    def __init__(self, *, database: Database, call_service: CallService) -> None:
        self.database = database
        self.call_service = call_service

    async def create_definition(
        self, definition: WorkflowDefinition
    ) -> WorkflowDefinitionRecord:
        async with self.database.session() as session:
            return await WorkflowRepository(session).create_definition(definition)

    async def start_run(self, *, definition_id: UUID, case_id: UUID) -> WorkflowRun:
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            definition_record = await repository.get_definition(definition_id)
            if definition_record is None:
                raise WorkflowDefinitionNotFoundError(str(definition_id))
            case = await CaseRepository(session).get_by_id(case_id)
            if case is None:
                raise CaseNotFoundError(str(case_id))
            return await repository.create_run(
                case_id=case_id,
                definition_record=definition_record,
            )

    async def advance_run(
        self, run_id: UUID, *, now: datetime | None = None
    ) -> WorkflowAdvanceResult:
        now = self._utc(now)
        run, step, existing_call_id, timer_id = await self._prepare_current_step(
            run_id, now=now
        )
        if timer_id is not None:
            return WorkflowAdvanceResult(
                run_id=run.id,
                status=WorkflowRunStatus(run.status),
                current_step_id=run.current_step_id,
                scheduled_timer_id=timer_id,
            )
        if step is None or step.kind != "call":
            return WorkflowAdvanceResult(
                run_id=run.id,
                status=WorkflowRunStatus(run.status),
                current_step_id=run.current_step_id,
            )
        call_step = step
        if call_step is None:
            return WorkflowAdvanceResult(
                run_id=run.id,
                status=WorkflowRunStatus(run.status),
                current_step_id=run.current_step_id,
            )
        if existing_call_id is not None:
            return WorkflowAdvanceResult(
                run_id=run.id,
                status=WorkflowRunStatus(run.status),
                current_step_id=run.current_step_id,
                scheduled_call_id=existing_call_id,
                scheduled_new_activity=False,
            )

        try:
            initiated = await self.call_service.initiate_call(
                call_step.to_number,
                agent_id=call_step.agent_id,
                case_id=run.case_id,
            )
        except (CallInitiationFailed, UnavailableAgentError) as exc:
            failure_code = (
                exc.provider_code
                if isinstance(exc, CallInitiationFailed)
                else "unavailable_agent"
            )
            await self._mark_call_activity_failed(
                run_id=run_id,
                step_id=call_step.id,
                failure_code=failure_code,
            )
            raise

        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            locked_run = await self._require_run_for_update(repository, run_id)
            attempt = await repository.get_attempt_by_key(
                run_id=run_id,
                idempotency_key=self._activity_key(
                    run_id,
                    call_step.id,
                    await repository.count_attempts_for_step(
                        run_id=run_id, step_id=call_step.id
                    ),
                ),
            )
            if attempt is None:
                attempt_number = (
                    await repository.count_attempts_for_step(
                        run_id=run_id, step_id=call_step.id
                    )
                    + 1
                )
                attempt = await repository.create_activity_attempt(
                    run=locked_run,
                    step_id=call_step.id,
                    kind=call_step.kind,
                    attempt_number=attempt_number,
                    idempotency_key=self._activity_key(
                        run_id, call_step.id, attempt_number
                    ),
                )
            await repository.mark_attempt_scheduled(
                attempt=attempt,
                call_id=initiated.id,
            )
            updated = await repository.transition_run(
                locked_run,
                WorkflowRunStatus.WAITING,
                last_call_id=initiated.id,
            )

        return WorkflowAdvanceResult(
            run_id=updated.id,
            status=WorkflowRunStatus(updated.status),
            current_step_id=updated.current_step_id,
            scheduled_call_id=initiated.id,
            scheduled_new_activity=True,
        )

    async def complete_call_activity(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        call_status: str | CallStatus = CallStatus.COMPLETED,
        outcome: CallOutcome | None = None,
        now: datetime | None = None,
    ) -> WorkflowRun:
        now = self._utc(now)
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            run = await self._require_run_for_update(repository, run_id)
            if run.last_call_id == call_id and run.status in {
                status.value for status in TERMINAL_WORKFLOW_STATUSES
            }:
                return run
            definition = WorkflowDefinition.model_validate(run.definition_snapshot)
            if run.current_step_id not in definition.steps_by_id:
                raise WorkflowActivityMismatchError("current step is not defined")
            step = definition.steps_by_id[run.current_step_id]
            if step.kind != "call":
                if run.last_call_id == call_id:
                    return run
                raise WorkflowActivityMismatchError(
                    "current step is not a call activity"
                )
            attempt = await repository.get_scheduled_attempt_for_step(
                run_id=run_id, step_id=step.id
            )
            if attempt is None or attempt.call_id != call_id:
                raise WorkflowActivityMismatchError(
                    "call does not match activity attempt"
                )
            normalized_status = CallStatus(call_status)
            await repository.mark_attempt_completed(
                attempt=attempt,
                outcome=outcome.model_dump(mode="json")
                if outcome is not None
                else None,
            )

            if (
                outcome is not None
                and outcome.kind is CallOutcomeKind.CALLBACK_REQUESTED
            ):
                callback_at = self._utc(outcome.callback_at)
                wake_step_id = step.callback_step_id or step.id
                await repository.create_timer(
                    run=run,
                    step_id=step.id,
                    kind="callback",
                    due_at=callback_at,
                    wake_step_id=wake_step_id,
                    idempotency_key=f"workflow-run:{run.id}:callback:{call_id}",
                    payload={
                        "call_id": str(call_id),
                        "callback_at": callback_at.isoformat(),
                    },
                )
                return await repository.transition_run(
                    run,
                    WorkflowRunStatus.WAITING,
                    last_call_id=call_id,
                )

            retry_due_at = self._retry_due_at(
                step=step,
                call_status=normalized_status,
                attempt_number=attempt.attempt_number,
                now=now,
            )
            if retry_due_at is not None:
                await repository.create_timer(
                    run=run,
                    step_id=step.id,
                    kind="retry",
                    due_at=retry_due_at,
                    wake_step_id=step.id,
                    idempotency_key=(
                        f"workflow-run:{run.id}:retry:{step.id}:"
                        f"{attempt.attempt_number}"
                    ),
                    payload={
                        "call_id": str(call_id),
                        "attempt_number": attempt.attempt_number,
                        "call_status": normalized_status.value,
                    },
                )
                return await repository.transition_run(
                    run,
                    WorkflowRunStatus.WAITING,
                    last_call_id=call_id,
                )

            next_step_id = self._next_step_for_call_status(step, normalized_status)
            if next_step_id is None:
                return await repository.transition_run(
                    run,
                    WorkflowRunStatus.FAILED,
                    last_call_id=call_id,
                    failure_code=f"call_{normalized_status.value}",
                )
            return await self._move_to_step(
                repository=repository,
                run=run,
                definition=definition,
                step_id=next_step_id,
                completed_step_id=step.id,
                last_call_id=call_id,
            )

    async def fire_due_timers(
        self, *, now: datetime | None = None, limit: int = 100
    ) -> list[WorkflowAdvanceResult]:
        now = self._utc(now)
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            timers = await repository.claim_due_timers(now=now, limit=limit)
            run_ids: list[UUID] = []
            for timer in timers:
                run = await repository.get_run_for_update(timer.run_id)
                if run is None:
                    continue
                if WorkflowRunStatus(run.status) in TERMINAL_WORKFLOW_STATUSES:
                    continue
                if timer.kind == "timeout":
                    subscription = await repository.mark_subscription_timed_out(
                        run_id=timer.run_id,
                        step_id=timer.step_id,
                    )
                    if subscription is None or subscription.on_timeout_step_id is None:
                        continue
                    wake_step_id = subscription.on_timeout_step_id
                else:
                    wake_step_id = timer.wake_step_id
                await repository.transition_run(
                    run,
                    WorkflowRunStatus.RUNNING,
                    current_step_id=wake_step_id,
                    completed_step_id=timer.step_id,
                )
                run_ids.append(run.id)

        results: list[WorkflowAdvanceResult] = []
        for run_id in run_ids:
            results.append(await self.advance_run(run_id, now=now))
        return results

    async def cancel_run(self, run_id: UUID) -> WorkflowRun:
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            run = await self._require_run_for_update(repository, run_id)
            await repository.cancel_pending_timers_for_run(run_id)
            await repository.cancel_pending_event_subscriptions_for_run(run_id)
            return await repository.transition_run(run, WorkflowRunStatus.CANCELLED)

    async def pause_run(self, run_id: UUID) -> WorkflowRun:
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            run = await self._require_run_for_update(repository, run_id)
            return await repository.transition_run(run, WorkflowRunStatus.PAUSED)

    async def resume_run(
        self, run_id: UUID, *, now: datetime | None = None
    ) -> WorkflowAdvanceResult:
        now = self._utc(now)
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            run = await self._require_run_for_update(repository, run_id)
            await repository.transition_run(run, WorkflowRunStatus.RUNNING)
        return await self.advance_run(run_id, now=now)

    async def ingest_external_event(
        self,
        *,
        event_type: str,
        correlation_key: str,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
        provided_secret: str | None = None,
        expected_secret: str | None = None,
        now: datetime | None = None,
    ) -> ExternalEventIngestResult:
        self._validate_external_event(
            event_type=event_type,
            correlation_key=correlation_key,
            idempotency_key=idempotency_key,
            provided_secret=provided_secret,
            expected_secret=expected_secret,
        )
        now = self._utc(now)
        run_id: UUID | None = None
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            event, created = await repository.create_external_event(
                event_type=event_type,
                correlation_key=correlation_key,
                idempotency_key=idempotency_key,
                payload=payload,
            )
            if not created:
                matched_run_id = None
                if event.subscription_id is not None:
                    subscription = await repository.get_event_subscription_by_id(
                        event.subscription_id
                    )
                    matched_run_id = (
                        subscription.run_id if subscription is not None else None
                    )
                return ExternalEventIngestResult(
                    event_id=event.id,
                    matched_run_id=matched_run_id,
                    was_duplicate=True,
                )
            subscription = await repository.get_pending_event_subscription_for_update(
                event_type=event_type,
                correlation_key=correlation_key,
            )
            if subscription is None:
                return ExternalEventIngestResult(
                    event_id=event.id,
                    matched_run_id=None,
                )
            run = await repository.get_run_for_update(subscription.run_id)
            if (
                run is None
                or WorkflowRunStatus(run.status) in TERMINAL_WORKFLOW_STATUSES
            ):
                return ExternalEventIngestResult(event_id=event.id, matched_run_id=None)
            await repository.mark_external_event_matched(
                event=event,
                subscription_id=subscription.id,
            )
            await repository.mark_subscription_consumed(
                subscription=subscription,
                event_id=event.id,
            )
            await repository.cancel_pending_timers_for_run(run.id)
            await repository.transition_run(
                run,
                WorkflowRunStatus.RUNNING,
                current_step_id=subscription.on_event_step_id,
                completed_step_id=subscription.step_id,
            )
            run_id = run.id

        if run_id is not None:
            await self.advance_run(run_id, now=now)
        return ExternalEventIngestResult(
            event_id=event.id,
            matched_run_id=run_id,
        )

    async def _prepare_current_step(
        self, run_id: UUID, *, now: datetime
    ) -> tuple[WorkflowRun, WorkflowStep | None, UUID | None, UUID | None]:
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            run = await self._require_run_for_update(repository, run_id)
            status = WorkflowRunStatus(run.status)
            if status in TERMINAL_WORKFLOW_STATUSES:
                raise WorkflowRunTerminalError(str(run_id))
            definition = WorkflowDefinition.model_validate(run.definition_snapshot)
            step = definition.steps_by_id[run.current_step_id]
            if status == WorkflowRunStatus.PENDING:
                run = await repository.transition_run(run, WorkflowRunStatus.RUNNING)
            if step.kind == "complete":
                run = await repository.transition_run(
                    run,
                    WorkflowRunStatus.COMPLETED,
                    completed_step_id=step.id,
                )
                return run, None, None, None
            if step.kind == "wait":
                timer = await self._schedule_wait_timer(
                    repository=repository,
                    run=run,
                    step=step,
                    now=now,
                )
                run = await repository.transition_run(run, WorkflowRunStatus.WAITING)
                return run, step, None, timer.id
            if step.kind == "wait_for_event":
                timer_id = await self._subscribe_to_external_event(
                    repository=repository,
                    run=run,
                    step=step,
                    now=now,
                )
                run = await repository.transition_run(run, WorkflowRunStatus.WAITING)
                return run, step, None, timer_id
            scheduled_attempt = await repository.get_scheduled_attempt_for_step(
                run_id=run_id, step_id=step.id
            )
            if scheduled_attempt is not None and scheduled_attempt.call_id is not None:
                return run, step, scheduled_attempt.call_id, None
            attempt_number = (
                await repository.count_attempts_for_step(run_id=run_id, step_id=step.id)
                + 1
            )
            attempt = await repository.create_activity_attempt(
                run=run,
                step_id=step.id,
                kind=step.kind,
                attempt_number=attempt_number,
                idempotency_key=self._activity_key(run_id, step.id, attempt_number),
            )
            if attempt.call_id is not None:
                return run, step, attempt.call_id, None
            return run, step, None, None

    async def _schedule_wait_timer(
        self,
        *,
        repository: WorkflowRepository,
        run: WorkflowRun,
        step: WaitStepDefinition,
        now: datetime,
    ):
        return await repository.create_timer(
            run=run,
            step_id=step.id,
            kind="wait",
            due_at=now + timedelta(seconds=step.delay_seconds),
            wake_step_id=step.next_step_id,
            idempotency_key=f"workflow-run:{run.id}:wait:{step.id}",
            payload={"delay_seconds": step.delay_seconds},
        )

    async def _subscribe_to_external_event(
        self,
        *,
        repository: WorkflowRepository,
        run: WorkflowRun,
        step: WaitForEventStepDefinition,
        now: datetime,
    ) -> UUID | None:
        await repository.create_event_subscription(
            run=run,
            step_id=step.id,
            event_type=step.event_type,
            correlation_key=step.correlation_key,
            on_event_step_id=step.on_event_step_id,
            on_timeout_step_id=step.on_timeout_step_id,
        )
        if step.timeout_seconds is None:
            return None
        timer = await repository.create_timer(
            run=run,
            step_id=step.id,
            kind="timeout",
            due_at=now + timedelta(seconds=step.timeout_seconds),
            wake_step_id=step.on_timeout_step_id or step.on_event_step_id,
            idempotency_key=f"workflow-run:{run.id}:event-timeout:{step.id}",
            payload={
                "event_type": step.event_type,
                "correlation_key": step.correlation_key,
                "timeout_seconds": step.timeout_seconds,
            },
        )
        return timer.id

    @staticmethod
    async def _require_run_for_update(
        repository: WorkflowRepository, run_id: UUID
    ) -> WorkflowRun:
        run = await repository.get_run_for_update(run_id)
        if run is None:
            raise WorkflowRunNotFoundError(str(run_id))
        return run

    @staticmethod
    def _activity_key(run_id: UUID, step_id: str, attempt_number: int) -> str:
        return f"workflow-run:{run_id}:step:{step_id}:call:{attempt_number}"

    async def _mark_call_activity_failed(
        self,
        *,
        run_id: UUID,
        step_id: str,
        failure_code: str,
    ) -> None:
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            locked_run = await self._require_run_for_update(repository, run_id)
            attempt_number = await repository.count_attempts_for_step(
                run_id=run_id, step_id=step_id
            )
            attempt = None
            if attempt_number > 0:
                attempt = await repository.get_attempt_by_key(
                    run_id=run_id,
                    idempotency_key=self._activity_key(run_id, step_id, attempt_number),
                )
            if attempt is not None:
                await repository.mark_attempt_failed(
                    attempt=attempt,
                    failure_code=failure_code,
                )
            await repository.transition_run(
                locked_run,
                WorkflowRunStatus.FAILED,
                failure_code=failure_code,
            )

    async def _move_to_step(
        self,
        *,
        repository: WorkflowRepository,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        step_id: str,
        completed_step_id: str,
        last_call_id: UUID | None = None,
    ) -> WorkflowRun:
        run = await repository.transition_run(
            run,
            WorkflowRunStatus.RUNNING,
            current_step_id=step_id,
            completed_step_id=completed_step_id,
            last_call_id=last_call_id,
        )
        next_step = definition.steps_by_id[run.current_step_id]
        if next_step.kind == "complete":
            return await repository.transition_run(
                run,
                WorkflowRunStatus.COMPLETED,
                completed_step_id=next_step.id,
            )
        return run

    @staticmethod
    def _next_step_for_call_status(
        step: CallActivityDefinition,
        call_status: CallStatus,
    ) -> str | None:
        if call_status in {CallStatus.COMPLETED, CallStatus.IN_PROGRESS}:
            return step.next_step_id
        if call_status == CallStatus.BUSY:
            return step.on_busy_step_id
        if call_status == CallStatus.NO_ANSWER:
            return step.on_no_answer_step_id
        if call_status == CallStatus.FAILED:
            return step.on_failed_step_id
        return None

    @staticmethod
    def _retry_due_at(
        *,
        step: CallActivityDefinition,
        call_status: CallStatus,
        attempt_number: int,
        now: datetime,
    ) -> datetime | None:
        policy = step.retry_policy
        if call_status.value not in policy.retry_on:
            return None
        if attempt_number >= policy.max_attempts:
            return None
        multiplier = 1
        if policy.backoff == "exponential":
            multiplier = 2 ** (attempt_number - 1)
        return now + timedelta(seconds=policy.delay_seconds * multiplier)

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _validate_external_event(
        *,
        event_type: str,
        correlation_key: str,
        idempotency_key: str,
        provided_secret: str | None,
        expected_secret: str | None,
    ) -> None:
        if expected_secret is not None and provided_secret != expected_secret:
            raise ExternalEventAuthenticationError("invalid external event secret")
        for label, value in {
            "event_type": event_type,
            "correlation_key": correlation_key,
            "idempotency_key": idempotency_key,
        }.items():
            if not value or not value.strip():
                raise ExternalEventValidationError(f"{label} is required")
