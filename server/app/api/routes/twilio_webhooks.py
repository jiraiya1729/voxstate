"""Twilio HTTP webhook routes.

This file verifies and handles inbound voice webhooks, call lifecycle callbacks, and
human-transfer status callbacks.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, ValidationError

from app.agents.errors import RoutingAmbiguityError, RoutingNoMatchError
from app.api.dependencies import (
    get_call_lifecycle_service,
    get_inbound_call_service,
    get_transfer_service,
    get_twilio_webhook_verifier,
)
from app.calls.inbound import InboundCallService
from app.calls.lifecycle import (
    ProviderCallMismatchError,
    UnknownCallError,
    UnsupportedProviderStatus,
)
from app.calls.lifecycle_service import CallLifecycleService
from app.calls.transfers import (
    TransferConflictError,
    TransferNotFoundError,
    TransferService,
)
from app.core.types import E164number
from app.voice.twilio.gateway import (
    TwilioWebhookVerifier,
    build_media_stream_twiml,
    build_rejected_call_twiml,
)

router = APIRouter(prefix="/webhooks/twilio", tags=["twilio-webhooks"])


class TwilioCallStatusPayload(BaseModel):
    """Form payload Twilio sends for outbound call lifecycle updates."""

    call_sid: str = Field(alias="CallSid", min_length=1)
    call_status: str = Field(alias="CallStatus", min_length=1)


class TwilioInboundPayload(BaseModel):
    """Form payload Twilio sends when Voxstate receives an inbound call."""

    call_sid: str = Field(alias="CallSid", min_length=1)
    from_number: E164number = Field(alias="From")
    to_number: E164number = Field(alias="To")
    language: str | None = Field(default=None, alias="Language")
    category: str | None = Field(default=None, alias="Category")


class TwilioTransferStatusPayload(BaseModel):
    """Form payload Twilio sends after a human Dial transfer changes state."""

    dial_call_status: str = Field(alias="DialCallStatus", min_length=1)


@router.post("/voice")
async def receive_inbound_call(
    request: Request,
    service: Annotated[InboundCallService, Depends(get_inbound_call_service)],
    verifier: Annotated[TwilioWebhookVerifier, Depends(get_twilio_webhook_verifier)],
    twilio_signature: Annotated[str | None, Header(alias="X-Twilio-Signature")] = None,
) -> Response:
    """Verify, route, persist, and connect an inbound Twilio call to media streaming."""
    form = await request.form()
    parameters = {key: str(value) for key, value in form.items()}
    if twilio_signature is None or not verifier.validate_inbound_voice(
        parameters=parameters, signature=twilio_signature
    ):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    try:
        payload = TwilioInboundPayload.model_validate(parameters)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail="Invalid Twilio inbound payload"
        ) from exc
    try:
        accepted = await service.accept(
            provider_call_id=payload.call_sid,
            from_number=payload.from_number,
            to_number=payload.to_number,
            language=payload.language,
            category=payload.category,
        )
    except (RoutingNoMatchError, RoutingAmbiguityError):
        return Response(
            content=build_rejected_call_twiml(), media_type="application/xml"
        )
    except ProviderCallMismatchError as exc:
        raise HTTPException(
            status_code=409, detail="Provider call ID does not match"
        ) from exc
    return Response(
        content=build_media_stream_twiml(verifier.public_base_url, accepted.id),
        media_type="application/xml",
    )


@router.post("/transfers/{transfer_id}/status", status_code=204)
async def receive_transfer_status(
    transfer_id: UUID,
    request: Request,
    service: Annotated[TransferService, Depends(get_transfer_service)],
    verifier: Annotated[TwilioWebhookVerifier, Depends(get_twilio_webhook_verifier)],
    twilio_signature: Annotated[str | None, Header(alias="X-Twilio-Signature")] = None,
) -> Response:
    """Apply Twilio's status callback for a human transfer attempt."""
    form = await request.form()
    parameters = {key: str(value) for key, value in form.items()}
    if twilio_signature is None or not verifier.validate_transfer_status(
        transfer_id=transfer_id, parameters=parameters, signature=twilio_signature
    ):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    try:
        payload = TwilioTransferStatusPayload.model_validate(parameters)
        await service.apply_human_status(transfer_id, payload.dial_call_status)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail="Invalid transfer status payload"
        ) from exc
    except TransferNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Transfer not found") from exc
    except TransferConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


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
    """Apply Twilio's lifecycle callback to a persisted call."""

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
