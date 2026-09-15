"""SQLAlchemy models for voice agents and deterministic routing configuration."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Agent(Base):
    """Persisted voice-agent configuration used to build per-call runtime behavior."""

    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False, default="en")
    bedrock_model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    bedrock_timeout_seconds: Mapped[float] = mapped_column(nullable=False, default=20.0)
    cartesia_voice_id: Mapped[str] = mapped_column(String(255), nullable=False)
    cartesia_tts_model_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="sonic-latest"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PhoneNumberRoute(Base):
    """Exact or fallback phone-number mapping from Twilio destination to an agent."""

    __tablename__ = "phone_number_routes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    phone_number: Mapped[str | None] = mapped_column(String(32), unique=True)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class RoutingRule(Base):
    """Ranked deterministic routing rule based on number, language, or category."""

    __tablename__ = "routing_rules"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    called_number: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
