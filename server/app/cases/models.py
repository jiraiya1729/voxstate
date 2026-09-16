"""SQLAlchemy models for durable business cases."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Case(Base):
    """One durable customer/business journey that can own multiple calls."""

    __tablename__ = "cases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    customer_reference_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open", server_default="open"
    )
    business_state: Mapped[str] = mapped_column(
        String(64), nullable=False, default="new", server_default="new"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_outcome: Mapped[dict[str, object] | None] = mapped_column(JSON)
    callback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_state: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
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
