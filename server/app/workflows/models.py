"""SQLAlchemy models for durable workflow definitions, runs, and activities."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowDefinitionRecord(Base):
    """Persisted workflow definition document."""

    __tablename__ = "workflow_definitions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    definition: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkflowRun(Base):
    """One durable execution pinned to a definition snapshot and case."""

    __tablename__ = "workflow_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"), nullable=False)
    definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_definitions.id"), nullable=False
    )
    definition_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    current_step_id: Mapped[str] = mapped_column(String(80), nullable=False)
    completed_step_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    last_call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id"))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkflowActivityAttempt(Base):
    """Durable attempt record for an external workflow activity effect."""

    __tablename__ = "workflow_activity_attempts"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "idempotency_key", name="uq_workflow_activity_attempt_effect"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_runs.id"), nullable=False)
    step_id: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id"))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkflowTimer(Base):
    """Persisted wakeup for waits, retries, and callbacks."""

    __tablename__ = "workflow_timers"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_workflow_timer_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_runs.id"), nullable=False)
    step_id: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wake_step_id: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
