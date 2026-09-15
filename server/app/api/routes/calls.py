"""Outbound call API route.

This file validates call-start requests, invokes the outbound call service, and maps
provider or agent-selection failures into HTTP responses.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_call_service
from app.calls.outbound import CallInitiationFailed, CallService, UnavailableAgentError
from app.calls.schemas import CallResponse, CreateCallRequest

router = APIRouter(prefix="/calls", tags=["calls"])


@router.post(
    "",
    response_model=CallResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_call(
    request: CreateCallRequest,
    service: Annotated[CallService, Depends(get_call_service)],
) -> CallResponse:
    """Start an outbound call and map provider failures to HTTP errors."""
    try:
        call = await service.initiate_call(request.to, request.agent_id)
    except UnavailableAgentError as exc:
        raise HTTPException(status_code=422, detail="Agent is unavailable") from exc
    except CallInitiationFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "telephony_provider_error",
                "call_id": str(exc.call_id),
                "provider_code": exc.provider_code,
            },
        ) from exc

    assert call.agent_id is not None
    return CallResponse(
        id=call.id,
        status=call.status,
        provider_call_id=call.provider_call_id,
        agent_id=call.agent_id,
    )
