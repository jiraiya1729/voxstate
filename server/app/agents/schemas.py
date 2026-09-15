"""Pydantic schemas for agent, phone-route, and routing-rule APIs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.types import E164number

TrimmedText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
LanguageTag = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$"
    ),
]


class AgentCreate(BaseModel):
    """Validated API payload for creating a selectable voice agent."""

    name: Annotated[TrimmedText, Field(max_length=120)]
    system_prompt: Annotated[TrimmedText, Field(max_length=20_000)]
    language: LanguageTag = "en"
    bedrock_model_id: Annotated[TrimmedText, Field(max_length=255)]
    bedrock_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    cartesia_voice_id: Annotated[TrimmedText, Field(max_length=255)]
    cartesia_tts_model_id: Annotated[TrimmedText, Field(max_length=64)] = "sonic-latest"
    enabled: bool = True


class AgentUpdate(BaseModel):
    """Partial API payload for editing an existing voice agent."""

    name: Annotated[TrimmedText, Field(max_length=120)] | None = None
    system_prompt: Annotated[TrimmedText, Field(max_length=20_000)] | None = None
    language: LanguageTag | None = None
    bedrock_model_id: Annotated[TrimmedText, Field(max_length=255)] | None = None
    bedrock_timeout_seconds: float | None = Field(default=None, gt=0, le=120)
    cartesia_voice_id: Annotated[TrimmedText, Field(max_length=255)] | None = None
    cartesia_tts_model_id: Annotated[TrimmedText, Field(max_length=64)] | None = None
    enabled: bool | None = None


class AgentResponse(AgentCreate):
    """API response shape for persisted agents."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime


class PhoneRouteCreate(BaseModel):
    """API payload for exact phone-number routes or the fallback route."""

    phone_number: E164number | None = None
    agent_id: UUID
    enabled: bool = True


class PhoneRouteResponse(PhoneRouteCreate):
    """API response shape for persisted phone-number routes."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID


class RoutingRuleCreate(BaseModel):
    """API payload for a ranked deterministic routing rule."""

    called_number: E164number | None = None
    language: LanguageTag | None = None
    category: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
        ]
        | None
    ) = None
    priority: int = Field(default=0, ge=-10_000, le=10_000)
    agent_id: UUID
    enabled: bool = True

    @model_validator(mode="after")
    def require_signal(self) -> "RoutingRuleCreate":
        """Require at least one matching signal so a rule is not meaningless."""
        if (
            self.called_number is None
            and self.language is None
            and self.category is None
        ):
            raise ValueError("at least one routing signal is required")
        return self


class RoutingRuleResponse(RoutingRuleCreate):
    """API response shape for persisted routing rules."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
