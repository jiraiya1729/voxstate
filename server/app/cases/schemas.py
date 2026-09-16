"""Pydantic schemas for durable case state."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.calls.outcomes import CallOutcome

CaseText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CaseStatus(StrEnum):
    """Legal durable case lifecycle statuses."""

    OPEN = "open"
    WAITING = "waiting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CaseCreate(BaseModel):
    """Validated payload for starting a durable case."""

    customer_reference_id: Annotated[CaseText, Field(max_length=128)]
    business_state: Annotated[CaseText, Field(max_length=64)] = "new"
    customer_state: dict[str, Any] = Field(default_factory=dict)


class CaseStateUpdate(BaseModel):
    """Partial durable state update for a case."""

    model_config = ConfigDict(extra="forbid")

    status: CaseStatus | None = None
    business_state: Annotated[CaseText, Field(max_length=64)] | None = None
    attempt_count: int | None = Field(default=None, ge=0)
    last_outcome: CallOutcome | None = None
    callback_at: datetime | None = None
    customer_state: dict[str, Any] | None = None

    @model_validator(mode="after")
    def keep_callback_consistent_with_outcome(self) -> "CaseStateUpdate":
        if self.last_outcome is None:
            return self
        if self.last_outcome.callback_at is not None and self.callback_at is None:
            self.callback_at = self.last_outcome.callback_at
        return self


class CaseResponse(BaseModel):
    """API-safe representation of one persisted case."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_reference_id: str
    status: CaseStatus
    business_state: str
    attempt_count: int
    last_outcome: dict[str, Any] | None
    callback_at: datetime | None
    customer_state: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime
