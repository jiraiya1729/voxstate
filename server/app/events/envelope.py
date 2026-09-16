"""Validated event envelope contracts."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

EventType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
    ),
]


class EventCreate(BaseModel):
    """Command for appending one normalized immutable event."""

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    call_id: UUID | None = None
    correlation_id: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
        ]
        | None
    ) = None
    idempotency_key: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
        ]
        | None
    ) = None
    version: int = Field(default=1, ge=1)
    payload: dict[str, object] = Field(default_factory=dict)


class EventEnvelope(EventCreate):
    """Persisted event record returned by append/query operations."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence: int | None = None
    occurred_at: datetime

    @model_validator(mode="after")
    def require_sequence_for_call_events(self) -> "EventEnvelope":
        if self.call_id is not None and self.sequence is None:
            raise ValueError("call events require a sequence")
        if self.call_id is None and self.sequence is not None:
            raise ValueError("sequence is only valid for call events")
        return self
