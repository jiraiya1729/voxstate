"""Validated structured outcomes produced by completed voice calls."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator


class CallOutcomeKind(StrEnum):
    """Machine-readable normalized call outcome kinds."""

    COMPLETED = "completed"
    CALLBACK_REQUESTED = "callback_requested"
    NOT_INTERESTED = "not_interested"
    PROMISE_TO_PAY = "promise_to_pay"
    HUMAN_REQUIRED = "human_required"
    WRONG_NUMBER = "wrong_number"
    UNKNOWN = "unknown"


OutcomeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CallOutcome(BaseModel):
    """Structured summary of a conversation for deterministic downstream logic."""

    kind: CallOutcomeKind
    confidence: float | None = Field(default=None, ge=0, le=1)
    summary: Annotated[OutcomeText, Field(max_length=2_000)] | None = None
    callback_at: datetime | None = None
    promised_payment_date: datetime | None = None
    human_reason: Annotated[OutcomeText, Field(max_length=1_000)] | None = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> "CallOutcome":
        if self.kind is CallOutcomeKind.CALLBACK_REQUESTED and self.callback_at is None:
            raise ValueError("callback_requested requires callback_at")
        if self.kind is not CallOutcomeKind.CALLBACK_REQUESTED and self.callback_at:
            raise ValueError("callback_at is only valid for callback_requested")

        if self.kind is CallOutcomeKind.PROMISE_TO_PAY:
            if self.promised_payment_date is None:
                raise ValueError("promise_to_pay requires promised_payment_date")
        elif self.promised_payment_date is not None:
            raise ValueError("promised_payment_date is only valid for promise_to_pay")

        if self.kind is CallOutcomeKind.HUMAN_REQUIRED:
            if self.human_reason is None:
                raise ValueError("human_required requires human_reason")
        elif self.human_reason is not None:
            raise ValueError("human_reason is only valid for human_required")

        return self
