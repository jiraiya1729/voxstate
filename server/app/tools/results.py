"""Standardized result contracts for deterministic tool execution."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ToolResultStatus(StrEnum):
    """Machine-readable status of a backend tool execution."""

    SUCCESS = "success"
    RETRYABLE_ERROR = "retryable_error"
    PERMANENT_ERROR = "permanent_error"
    TIMEOUT = "timeout"


class ToolResult(BaseModel):
    """Typed result returned by every tool implementation."""

    status: ToolResultStatus
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    message: str | None = None
    retry_after_seconds: float | None = Field(default=None, gt=0)

    @classmethod
    def success(cls, data: dict[str, Any] | None = None) -> "ToolResult":
        return cls(status=ToolResultStatus.SUCCESS, data=data or {})

    @classmethod
    def retryable_error(
        cls,
        *,
        error_code: str,
        message: str,
        retry_after_seconds: float | None = None,
    ) -> "ToolResult":
        return cls(
            status=ToolResultStatus.RETRYABLE_ERROR,
            error_code=error_code,
            message=message,
            retry_after_seconds=retry_after_seconds,
        )

    @classmethod
    def permanent_error(cls, *, error_code: str, message: str) -> "ToolResult":
        return cls(
            status=ToolResultStatus.PERMANENT_ERROR,
            error_code=error_code,
            message=message,
        )

    @classmethod
    def timeout(cls, *, message: str = "tool execution timed out") -> "ToolResult":
        return cls(
            status=ToolResultStatus.TIMEOUT, error_code="timeout", message=message
        )

    @model_validator(mode="after")
    def validate_status_payload(self) -> "ToolResult":
        if self.status is ToolResultStatus.SUCCESS:
            if self.error_code is not None or self.message is not None:
                raise ValueError("successful tool results cannot include an error")
            if self.retry_after_seconds is not None:
                raise ValueError(
                    "successful tool results cannot include retry metadata"
                )
            return self

        if not self.error_code or not self.message:
            raise ValueError("failed tool results require an error_code and message")
        if self.data:
            raise ValueError("failed tool results cannot include success data")
        if (
            self.retry_after_seconds is not None
            and self.status is not ToolResultStatus.RETRYABLE_ERROR
        ):
            raise ValueError("retry metadata is only valid for retryable errors")
        return self
