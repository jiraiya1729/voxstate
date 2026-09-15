from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from twilio.request_validator import RequestValidator

import app.voice.twilio.gateway as twilio_module
from app.voice.twilio.gateway import (
    TwilioTelephonyGateway,
    TwilioWebhookVerifier,
    build_human_transfer_twiml,
    build_inbound_voice_url,
    build_media_stream_twiml,
    build_media_stream_url,
    build_status_callback_url,
    build_transfer_status_url,
)

CALL_ID = UUID("00000000-0000-0000-0000-000000000001")
PUBLIC_BASE_URL = "https://voxstate.example.com"


@pytest.mark.asyncio
async def test_twilio_gateway_constructs_media_stream_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeCalls:
        def create(self, **kwargs: Any) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(sid="CA00000000000000000000000000000001")

    class FakeClient:
        calls = FakeCalls()

    monkeypatch.setattr(
        twilio_module,
        "TwilioHttpClient",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        twilio_module,
        "Client",
        lambda *args, **kwargs: FakeClient(),
    )

    gateway = TwilioTelephonyGateway(
        account_sid="AC00000000000000000000000000000000",
        auth_token="secret",
        from_number="+15555550100",
        public_base_url=PUBLIC_BASE_URL,
    )

    result = await gateway.create_call(
        call_id=CALL_ID,
        to_number="+15555550114",
    )

    assert result.provider_call_id == ("CA00000000000000000000000000000001")
    assert captured["to"] == "+15555550114"
    assert captured["from_"] == "+15555550100"
    assert captured["twiml"] == build_media_stream_twiml(
        PUBLIC_BASE_URL,
        CALL_ID,
    )
    assert 'url="wss://voxstate.example.com/media/twilio"' in captured["twiml"]
    assert f'value="{CALL_ID}"' in captured["twiml"]
    assert captured["status_callback"] == build_status_callback_url(
        PUBLIC_BASE_URL,
        CALL_ID,
    )


def test_twilio_http_webhook_verifier_accepts_matching_signature() -> None:
    parameters = {
        "CallSid": "CA00000000000000000000000000000001",
        "CallStatus": "ringing",
    }
    callback_url = build_status_callback_url(PUBLIC_BASE_URL, CALL_ID)
    signature = RequestValidator("secret").compute_signature(
        callback_url,
        parameters,
    )
    verifier = TwilioWebhookVerifier(
        auth_token="secret",
        public_base_url=PUBLIC_BASE_URL,
    )

    assert verifier.validate(
        call_id=CALL_ID,
        parameters=parameters,
        signature=signature,
    )


def test_twilio_media_verifier_accepts_matching_signature() -> None:
    media_url = build_media_stream_url(PUBLIC_BASE_URL)
    signature = RequestValidator("secret").compute_signature(media_url, {})
    verifier = TwilioWebhookVerifier(
        auth_token="secret",
        public_base_url=PUBLIC_BASE_URL,
    )

    assert verifier.validate_media_stream(signature=signature)


def test_human_transfer_twiml_dials_validated_destination() -> None:
    transfer_id = UUID("00000000-0000-0000-0000-000000000002")
    twiml = build_human_transfer_twiml(PUBLIC_BASE_URL, transfer_id, "+15555550120")
    assert "<Dial" in twiml
    assert "+15555550120" in twiml
    assert (
        build_transfer_status_url(PUBLIC_BASE_URL, transfer_id).replace("&", "&amp;")
        in twiml
    )


def test_inbound_and_transfer_signatures_use_exact_urls() -> None:
    validator = RequestValidator("secret")
    verifier = TwilioWebhookVerifier(
        auth_token="secret", public_base_url=PUBLIC_BASE_URL
    )
    inbound = {"CallSid": "CA1", "From": "+15555550121", "To": "+15555550122"}
    assert verifier.validate_inbound_voice(
        parameters=inbound,
        signature=validator.compute_signature(
            build_inbound_voice_url(PUBLIC_BASE_URL), inbound
        ),
    )
    transfer_id = UUID("00000000-0000-0000-0000-000000000003")
    status = {"DialCallStatus": "completed"}
    assert verifier.validate_transfer_status(
        transfer_id=transfer_id,
        parameters=status,
        signature=validator.compute_signature(
            build_transfer_status_url(PUBLIC_BASE_URL, transfer_id), status
        ),
    )
