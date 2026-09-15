"""Pydantic request and response schemas for outbound call APIs."""

from uuid import UUID

from pydantic import BaseModel

from app.core.types import E164number


class CreateCallRequest(BaseModel):
    """HTTP payload for starting an outbound call through a selected agent."""

    to: E164number
    agent_id: UUID


class CallResponse(BaseModel):
    """HTTP response returned after Twilio accepts an outbound call request."""

    id: UUID
    status: str
    provider_call_id: str
    agent_id: UUID
