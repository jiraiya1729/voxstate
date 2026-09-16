"""Application service for the first durable workflow runtime."""

from dataclasses import dataclass
from uuid import UUID

from app.calls.outbound import CallInitiationFailed, CallService, UnavailableAgentError
from app.cases.errors import CaseNotFoundError
from app.cases.repository import CaseRepository
from app.db.database import Database
from app.workflows.definition import CallActivityDefinition, WorkflowDefinition
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


@dataclass(frozen=True)
class WorkflowAdvanceResult:
    """Compact result returned after advancing one workflow run."""

    run_id: UUID
    status: WorkflowRunStatus
    current_step_id: str
    scheduled_call_id: UUID | None = None
    scheduled_new_activity: bool = False


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

    async def advance_run(self, run_id: UUID) -> WorkflowAdvanceResult:
        run, call_step, existing_call_id = await self._prepare_current_step(run_id)
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
                idempotency_key=self._activity_key(run_id, call_step.id),
            )
            if attempt is None:
                attempt = await repository.create_activity_attempt(
                    run=locked_run,
                    step_id=call_step.id,
                    kind=call_step.kind,
                    idempotency_key=self._activity_key(run_id, call_step.id),
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
    ) -> WorkflowRun:
        async with self.database.session() as session:
            repository = WorkflowRepository(session)
            run = await self._require_run_for_update(repository, run_id)
            definition = WorkflowDefinition.model_validate(run.definition_snapshot)
            step = definition.steps_by_id[run.current_step_id]
            if step.kind != "call":
                raise WorkflowActivityMismatchError(
                    "current step is not a call activity"
                )
            attempt = await repository.get_attempt_by_key(
                run_id=run_id,
                idempotency_key=self._activity_key(run_id, step.id),
            )
            if attempt is None or attempt.call_id != call_id:
                raise WorkflowActivityMismatchError(
                    "call does not match activity attempt"
                )
            run = await repository.transition_run(
                run,
                WorkflowRunStatus.RUNNING,
                current_step_id=step.next_step_id,
                completed_step_id=step.id,
            )
            next_step = definition.steps_by_id[run.current_step_id]
            if next_step.kind == "complete":
                run = await repository.transition_run(
                    run,
                    WorkflowRunStatus.COMPLETED,
                    completed_step_id=next_step.id,
                )
            return run

    async def _prepare_current_step(
        self, run_id: UUID
    ) -> tuple[WorkflowRun, CallActivityDefinition | None, UUID | None]:
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
                return run, None, None
            attempt = await repository.create_activity_attempt(
                run=run,
                step_id=step.id,
                kind=step.kind,
                idempotency_key=self._activity_key(run_id, step.id),
            )
            if attempt.call_id is not None:
                return run, step, attempt.call_id
            return run, step, None

    @staticmethod
    async def _require_run_for_update(
        repository: WorkflowRepository, run_id: UUID
    ) -> WorkflowRun:
        run = await repository.get_run_for_update(run_id)
        if run is None:
            raise WorkflowRunNotFoundError(str(run_id))
        return run

    @staticmethod
    def _activity_key(run_id: UUID, step_id: str) -> str:
        return f"workflow-run:{run_id}:step:{step_id}:call"

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
            attempt = await repository.get_attempt_by_key(
                run_id=run_id,
                idempotency_key=self._activity_key(run_id, step_id),
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
