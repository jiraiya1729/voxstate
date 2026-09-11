from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, ValidationError

from app.api.dependencies import get_call_lifecycle_service, get_twilio_webhook_verifier
from app.calls.lifecycle import (
    ProviderCallMismatchError,
    UnknownCallError,
    UnsupportedProviderStatus,
)
from app.calls.service import CallLifecycleService
from app.voice.twilio import TwilioWebhookVerifier

router = APIRouter(prefix="/webhooks/twilio", tags=["twilio-webhooks"])


class TwilioCallStatusPayload(BaseModel):
    call_sid: str = Field(alias="CallSid", min_length=1)
    call_status: str = Field(alias="CallStatus", min_length=1)


@router.post("/calls/{call_id}/status", status_code=status.HTTP_204_NO_CONTENT)
async def receive_call_status(
    call_id: UUID,
    request: Request,
    lifecycle: Annotated[
        CallLifecycleService,
        Depends(get_call_lifecycle_service),
    ],
    verifier: Annotated[
        TwilioWebhookVerifier,
        Depends(get_twilio_webhook_verifier),
    ],
    twilio_signature: Annotated[str | None, Header(alias="X-Twilio-Signature")] = None,
) -> Response:

    form = await request.form()
    parameters = {key: str(value) for key, value in form.items()}

    if twilio_signature is None or not verifier.validate(
        call_id=call_id, parameters=parameters, signature=twilio_signature
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature"
        )

    try:
        payload = TwilioCallStatusPayload.model_validate(parameters)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid Twilio call status payload",
        ) from exc

    try:
        await lifecycle.apply_status_callback(
            call_id=call_id,
            provider_call_id=payload.call_sid,
            provider_status=payload.call_status,
        )
    except UnknownCallError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown call"
        ) from exc

    except ProviderCallMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider call ID does not match",
        ) from exc

    except UnsupportedProviderStatus as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported Twilio call status",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
