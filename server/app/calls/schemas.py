from uuid import UUID

from pydantic import BaseModel

from app.core.types import E164number


class CreateCallRequest(BaseModel):
    to: E164number


class CallResponse(BaseModel):
    id: UUID
    status: str
    provider_call_id: str
