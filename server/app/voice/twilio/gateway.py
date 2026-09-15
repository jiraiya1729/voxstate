"""Twilio gateway, TwiML builders, URL builders, and signature verification."""

import asyncio
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from requests import RequestException
from twilio.base.exceptions import TwilioException, TwilioRestException
from twilio.http.http_client import TwilioHttpClient
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

from app.calls.telephony import ProviderCall, TelephonyProviderError


def build_status_callback_url(public_base_url: str, call_id: UUID) -> str:
    """Build the signed Twilio status callback URL for one internal call."""
    base_url = public_base_url.rstrip("/")
    return f"{base_url}/webhooks/twilio/calls/{call_id}/status"


def build_inbound_voice_url(public_base_url: str) -> str:
    """Build the Twilio inbound voice webhook URL."""
    return f"{public_base_url.rstrip('/')}/webhooks/twilio/voice"


def build_transfer_status_url(public_base_url: str, transfer_id: UUID) -> str:
    """Build the Twilio Dial status callback URL for one transfer attempt."""
    return (
        f"{public_base_url.rstrip('/')}/webhooks/twilio/transfers/{transfer_id}/status"
    )


def build_human_transfer_twiml(
    public_base_url: str, transfer_id: UUID, to_number: str
) -> str:
    """Build TwiML that transfers the live call to a human phone number."""
    response = VoiceResponse()
    response.dial(
        to_number,
        action=build_transfer_status_url(public_base_url, transfer_id),
        method="POST",
    )
    return str(response)


def build_rejected_call_twiml() -> str:
    """Build TwiML that rejects an unroutable inbound call by hanging up."""
    response = VoiceResponse()
    response.hangup()
    return str(response)


def build_media_stream_url(public_base_url: str) -> str:
    """Convert the public HTTPS app URL into Twilio's media WebSocket URL."""
    parsed = urlsplit(public_base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Twilio Media Streams require a public HTTPS base URL")
    path = f"{parsed.path.rstrip('/')}/media/twilio"
    return urlunsplit(("wss", parsed.netloc, path, "", ""))


def build_media_stream_twiml(public_base_url: str, call_id: UUID) -> str:
    """Build TwiML that connects Twilio audio to Voxstate's media WebSocket."""
    response = VoiceResponse()
    connect = response.connect()
    stream = connect.stream(url=build_media_stream_url(public_base_url))
    stream.parameter(name="call_id", value=str(call_id))
    return str(response)


class TwilioWebhookVerifier:
    """Validates Twilio signatures for HTTP webhooks and media WebSocket starts."""

    def __init__(self, *, auth_token: str, public_base_url: str) -> None:
        self.validator = RequestValidator(auth_token)
        self.public_base_url = public_base_url

    def validate(
        self,
        *,
        call_id: UUID,
        parameters: Mapping[str, str],
        signature: str,
    ) -> bool:
        """Validate a call lifecycle status callback for one internal call."""
        callback_url = build_status_callback_url(
            self.public_base_url,
            call_id,
        )
        return self.validator.validate(callback_url, parameters, signature)

    def validate_media_stream(self, *, signature: str) -> bool:
        """Validate the signature Twilio sends when opening the media WebSocket."""
        return self.validator.validate(
            build_media_stream_url(self.public_base_url),
            {},
            signature,
        )

    def validate_inbound_voice(
        self, *, parameters: Mapping[str, str], signature: str
    ) -> bool:
        """Validate an inbound voice webhook before routing the call."""
        return self.validator.validate(
            build_inbound_voice_url(self.public_base_url), parameters, signature
        )

    def validate_transfer_status(
        self,
        *,
        transfer_id: UUID,
        parameters: Mapping[str, str],
        signature: str,
    ) -> bool:
        """Validate a Twilio Dial status callback for a human transfer."""
        return self.validator.validate(
            build_transfer_status_url(self.public_base_url, transfer_id),
            parameters,
            signature,
        )


class TwilioTelephonyGateway:
    """Twilio implementation of outbound call creation and live call transfer."""

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        public_base_url: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.public_base_url = public_base_url
        self.timeout_seconds = timeout_seconds

    async def create_call(
        self,
        *,
        call_id: UUID,
        to_number: str,
    ) -> ProviderCall:
        """Ask Twilio to start an outbound call and normalize provider errors."""
        try:
            twilio_call = await asyncio.to_thread(
                self._create_call,
                call_id,
                to_number,
            )
        except TwilioRestException as exc:
            code = (
                str(exc.code) if exc.code is not None else f"twilio_http_{exc.status}"
            )
            raise TelephonyProviderError(code) from exc
        except (TwilioException, RequestException, TimeoutError, OSError) as exc:
            raise TelephonyProviderError("twilio_unavailable") from exc

        provider_call_id = getattr(twilio_call, "sid", None)
        if not provider_call_id:
            raise TelephonyProviderError("twilio_missing_call_sid")
        return ProviderCall(provider_call_id)

    def _create_call(self, call_id: UUID, to_number: str) -> Any:
        """Blocking Twilio SDK call used behind asyncio.to_thread."""
        http_client = TwilioHttpClient(timeout=self.timeout_seconds)
        client = Client(
            self.account_sid,
            self.auth_token,
            http_client=http_client,
        )
        return client.calls.create(
            to=to_number,
            from_=self.from_number,
            twiml=build_media_stream_twiml(self.public_base_url, call_id),
            status_callback=build_status_callback_url(
                self.public_base_url,
                call_id,
            ),
            status_callback_method="POST",
            status_callback_event=[
                "initiated",
                "ringing",
                "answered",
                "completed",
            ],
        )

    async def transfer_call(
        self,
        *,
        provider_call_id: str,
        to_number: str,
        transfer_id: UUID,
    ) -> None:
        """Ask Twilio to update a live call with human-transfer TwiML."""
        try:
            await asyncio.to_thread(
                self._transfer_call, provider_call_id, to_number, transfer_id
            )
        except TwilioRestException as exc:
            code = (
                str(exc.code) if exc.code is not None else f"twilio_http_{exc.status}"
            )
            raise TelephonyProviderError(code) from exc
        except (TwilioException, RequestException, TimeoutError, OSError) as exc:
            raise TelephonyProviderError("twilio_unavailable") from exc

    def _transfer_call(
        self, provider_call_id: str, to_number: str, transfer_id: UUID
    ) -> Any:
        """Blocking Twilio SDK update used behind asyncio.to_thread."""
        http_client = TwilioHttpClient(timeout=self.timeout_seconds)
        client = Client(self.account_sid, self.auth_token, http_client=http_client)
        return client.calls(provider_call_id).update(
            twiml=build_human_transfer_twiml(
                self.public_base_url, transfer_id, to_number
            )
        )
