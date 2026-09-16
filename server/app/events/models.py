"""SQLAlchemy models for the append-only event ledger."""

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


class Event(Base):
    """One immutable event in a normalized aggregate history."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("call_id", "sequence", name="uq_events_call_sequence"),
        UniqueConstraint("idempotency_key", name="uq_events_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id"))
    sequence: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
