"""Database repository for durable workflow definitions and runs."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.workflows.definition import WorkflowDefinition
from app.workflows.models import (
    WorkflowActivityAttempt,
    WorkflowDefinitionRecord,
    WorkflowRun,
    WorkflowTimer,
)
from app.workflows.state import WorkflowRunStatus, resolve_workflow_transition


class WorkflowRepository:
    """Persistence boundary for workflow definitions, runs, and attempts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_definition(
        self, definition: WorkflowDefinition
    ) -> WorkflowDefinitionRecord:
        row = WorkflowDefinitionRecord(
            name=definition.name,
            definition=definition.model_dump(mode="json"),
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_definition(
        self, definition_id: UUID
    ) -> WorkflowDefinitionRecord | None:
        return await self.session.get(WorkflowDefinitionRecord, definition_id)

    async def create_run(
        self,
        *,
        case_id: UUID,
        definition_record: WorkflowDefinitionRecord,
    ) -> WorkflowRun:
        definition = WorkflowDefinition.model_validate(definition_record.definition)
        run = WorkflowRun(
            case_id=case_id,
            definition_id=definition_record.id,
            definition_snapshot=definition_record.definition,
            current_step_id=definition.initial_step_id,
        )
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def get_run(self, run_id: UUID) -> WorkflowRun | None:
        return await self.session.get(WorkflowRun, run_id)

    async def get_run_for_update(self, run_id: UUID) -> WorkflowRun | None:
        result = await self.session.execute(
            select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def transition_run(
        self,
        run: WorkflowRun,
        target_status: WorkflowRunStatus,
        *,
        current_step_id: str | None = None,
        completed_step_id: str | None = None,
        last_call_id: UUID | None = None,
        failure_code: str | None = None,
    ) -> WorkflowRun:
        next_status = resolve_workflow_transition(run.status, target_status)
        if next_status is not None:
            run.status = next_status.value
        if current_step_id is not None:
            run.current_step_id = current_step_id
        if completed_step_id is not None:
            completed = list(run.completed_step_ids)
            if completed_step_id not in completed:
                completed.append(completed_step_id)
            run.completed_step_ids = completed
        if last_call_id is not None:
            run.last_call_id = last_call_id
        if failure_code is not None:
            run.failure_code = failure_code
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def get_attempt_by_key(
        self, *, run_id: UUID, idempotency_key: str
    ) -> WorkflowActivityAttempt | None:
        result = await self.session.execute(
            select(WorkflowActivityAttempt).where(
                WorkflowActivityAttempt.run_id == run_id,
                WorkflowActivityAttempt.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def create_activity_attempt(
        self,
        *,
        run: WorkflowRun,
        step_id: str,
        kind: str,
        attempt_number: int,
        idempotency_key: str,
    ) -> WorkflowActivityAttempt:
        existing = await self.get_attempt_by_key(
            run_id=run.id, idempotency_key=idempotency_key
        )
        if existing is not None:
            return existing
        attempt = WorkflowActivityAttempt(
            run_id=run.id,
            step_id=step_id,
            kind=kind,
            attempt_number=attempt_number,
            idempotency_key=idempotency_key,
        )
        self.session.add(attempt)
        await self.session.flush()
        await self.session.refresh(attempt)
        return attempt

    async def count_attempts_for_step(self, *, run_id: UUID, step_id: str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(WorkflowActivityAttempt)
            .where(
                WorkflowActivityAttempt.run_id == run_id,
                WorkflowActivityAttempt.step_id == step_id,
                WorkflowActivityAttempt.kind == "call",
            )
        )
        return int(result.scalar_one())

    async def get_scheduled_attempt_for_step(
        self, *, run_id: UUID, step_id: str
    ) -> WorkflowActivityAttempt | None:
        result = await self.session.execute(
            select(WorkflowActivityAttempt)
            .where(
                WorkflowActivityAttempt.run_id == run_id,
                WorkflowActivityAttempt.step_id == step_id,
                WorkflowActivityAttempt.status == "scheduled",
            )
            .order_by(WorkflowActivityAttempt.attempt_number.desc())
        )
        return result.scalars().first()

    async def mark_attempt_scheduled(
        self,
        *,
        attempt: WorkflowActivityAttempt,
        call_id: UUID,
    ) -> WorkflowActivityAttempt:
        attempt.call_id = call_id
        attempt.status = "scheduled"
        attempt.failure_code = None
        await self.session.flush()
        await self.session.refresh(attempt)
        return attempt

    async def mark_attempt_failed(
        self,
        *,
        attempt: WorkflowActivityAttempt,
        failure_code: str,
    ) -> WorkflowActivityAttempt:
        attempt.status = "failed"
        attempt.failure_code = failure_code
        await self.session.flush()
        await self.session.refresh(attempt)
        return attempt

    async def mark_attempt_completed(
        self,
        *,
        attempt: WorkflowActivityAttempt,
        outcome: dict[str, object] | None = None,
    ) -> WorkflowActivityAttempt:
        attempt.status = "completed"
        attempt.failure_code = None
        attempt.outcome = outcome
        await self.session.flush()
        await self.session.refresh(attempt)
        return attempt

    async def create_timer(
        self,
        *,
        run: WorkflowRun,
        step_id: str,
        kind: str,
        due_at: datetime,
        wake_step_id: str,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
    ) -> WorkflowTimer:
        existing = await self.get_timer_by_key(idempotency_key)
        if existing is not None:
            return existing
        timer = WorkflowTimer(
            run_id=run.id,
            step_id=step_id,
            kind=kind,
            due_at=due_at,
            wake_step_id=wake_step_id,
            idempotency_key=idempotency_key,
            payload=payload or {},
        )
        self.session.add(timer)
        await self.session.flush()
        await self.session.refresh(timer)
        return timer

    async def get_timer_by_key(self, idempotency_key: str) -> WorkflowTimer | None:
        result = await self.session.execute(
            select(WorkflowTimer).where(
                WorkflowTimer.idempotency_key == idempotency_key
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_timer_for_step(
        self, *, run_id: UUID, step_id: str, kind: str
    ) -> WorkflowTimer | None:
        result = await self.session.execute(
            select(WorkflowTimer)
            .where(
                WorkflowTimer.run_id == run_id,
                WorkflowTimer.step_id == step_id,
                WorkflowTimer.kind == kind,
                WorkflowTimer.status == "pending",
            )
            .order_by(WorkflowTimer.due_at.asc(), WorkflowTimer.id.asc())
        )
        return result.scalars().first()

    async def claim_due_timers(
        self, *, now: datetime, limit: int = 100
    ) -> list[WorkflowTimer]:
        result = await self.session.execute(
            select(WorkflowTimer)
            .where(WorkflowTimer.status == "pending", WorkflowTimer.due_at <= now)
            .order_by(WorkflowTimer.due_at.asc(), WorkflowTimer.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        timers = list(result.scalars())
        for timer in timers:
            timer.status = "fired"
            timer.fired_at = now
        await self.session.flush()
        for timer in timers:
            await self.session.refresh(timer)
        return timers

    async def cancel_pending_timers_for_run(self, run_id: UUID) -> int:
        result = await self.session.execute(
            select(WorkflowTimer)
            .where(WorkflowTimer.run_id == run_id, WorkflowTimer.status == "pending")
            .with_for_update()
        )
        timers = list(result.scalars())
        for timer in timers:
            timer.status = "cancelled"
        await self.session.flush()
        return len(timers)
