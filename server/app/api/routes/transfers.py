"""Live call transfer API routes.

This file exposes idempotent commands for AI-agent or human phone handoff.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_transfer_service
from app.calls.transfers import (
    TransferConflictError,
    TransferNotFoundError,
    TransferProviderError,
    TransferResult,
    TransferService,
)
from app.core.types import E164number

router = APIRouter(prefix="/calls/{call_id}/transfers", tags=["call-transfers"])


class AgentTransferRequest(BaseModel):
    """HTTP payload for transferring a live call to another agent."""

    target_agent_id: UUID


class HumanTransferRequest(BaseModel):
    """HTTP payload for transferring a live call to a human phone number."""

    to: E164number


class TransferResponse(BaseModel):
    """HTTP response shape for agent and human transfer attempts."""

    id: UUID
    status: str
    kind: str
    failure_code: str | None = None


def _response(result: TransferResult) -> TransferResponse:
    """Convert a transfer service result into the API response model."""
    return TransferResponse(
        id=result.id,
        status=result.status,
        kind=result.kind,
        failure_code=result.failure_code,
    )


def _map_error(exc: Exception) -> HTTPException:
    """Map transfer-domain errors to route-level HTTP responses."""
    if isinstance(exc, TransferNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TransferProviderError):
        return HTTPException(
            status_code=502,
            detail={"code": "transfer_provider_error", "provider_code": str(exc)},
        )
    return HTTPException(status_code=409, detail=str(exc))


@router.post("/agent", response_model=TransferResponse)
async def transfer_agent(
    call_id: UUID,
    data: AgentTransferRequest,
    service: Annotated[TransferService, Depends(get_transfer_service)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
) -> TransferResponse:
    """Transfer an active AI call to another enabled agent."""
    try:
        return _response(
            await service.transfer_to_agent(
                call_id=call_id,
                target_agent_id=data.target_agent_id,
                idempotency_key=idempotency_key,
            )
        )
    except (TransferNotFoundError, TransferConflictError) as exc:
        raise _map_error(exc) from exc


@router.post("/human", response_model=TransferResponse)
async def transfer_human(
    call_id: UUID,
    data: HumanTransferRequest,
    service: Annotated[TransferService, Depends(get_transfer_service)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
) -> TransferResponse:
    """Transfer an active AI call to a human destination through Twilio."""
    try:
        return _response(
            await service.transfer_to_human(
                call_id=call_id, to_number=data.to, idempotency_key=idempotency_key
            )
        )
    except (TransferNotFoundError, TransferConflictError, TransferProviderError) as exc:
        raise _map_error(exc) from exc
