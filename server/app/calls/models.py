"""SQLAlchemy models for calls and transfer attempts.

This file defines the persisted call lifecycle state, provider correlation fields,
agent pointers, and idempotent transfer history.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Call(Base):
    """One persisted telephony conversation and its current provider lifecycle state."""

    __tablename__ = "calls"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    to_phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    from_phone_number: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(
        String(16), nullable=False, default="outbound"
    )
    initial_agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id"))
    active_agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id"))
    case_id: Mapped[UUID | None] = mapped_column(ForeignKey("cases.id"))
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    provider_call_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
    )
    failure_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CallTransfer(Base):
    """Transfer attempt history keyed for idempotent agent or human handoff retries."""

    __tablename__ = "call_transfers"
    __table_args__ = (
        UniqueConstraint(
            "call_id", "idempotency_key", name="uq_call_transfer_idempotency"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id"))
    target_agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id"))
    target_phone_number: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
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
