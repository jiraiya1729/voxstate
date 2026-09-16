"""Strict input schemas for backend-owned voice tools."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ToolText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ToolInput(BaseModel):
    """Base class for model-generated tool arguments."""

    model_config = ConfigDict(extra="forbid")


class GetCustomerInput(ToolInput):
    """Arguments for loading a customer record."""

    customer_id: Annotated[ToolText, Field(max_length=128)]


class CheckPaymentInput(ToolInput):
    """Arguments for checking payment status by customer or account."""

    customer_id: Annotated[ToolText, Field(max_length=128)] | None = None
    account_id: Annotated[ToolText, Field(max_length=128)] | None = None

    @model_validator(mode="after")
    def require_identifier(self) -> "CheckPaymentInput":
        if self.customer_id is None and self.account_id is None:
            raise ValueError("customer_id or account_id is required")
        return self


class CreateTicketInput(ToolInput):
    """Arguments for creating a support ticket from a call."""

    customer_id: Annotated[ToolText, Field(max_length=128)]
    title: Annotated[ToolText, Field(max_length=200)]
    description: Annotated[ToolText, Field(max_length=4_000)]
    priority: str = Field(default="normal", pattern=r"^(low|normal|high|urgent)$")
