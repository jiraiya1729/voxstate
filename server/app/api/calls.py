from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_call_service
from app.calls.schemas import CallResponse, CreateCallRequest
from app.calls.service import CallInitiationFailed, CallService

router = APIRouter(prefix="/calls", tags=["calls"])


@router.post("", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def create_call(
    request: CreateCallRequest,
    service: Annotated[CallService, Depends(get_call_service)],
) -> CallResponse:
    try:
        call = await service.initiate_call(request.to)
    except CallInitiationFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "telephony_provider_error",
                "call_id": str(exc.call_id),
                "provider_code": exc.provider_code,
            },
        ) from exc

    return CallResponse(
        id=call.id, status=call.status, provider_call_id=call.provider_call_id
    )
