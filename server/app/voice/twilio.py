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
    base_url = public_base_url.rstrip("/")
    return f"{base_url}/webhooks/twilio/calls/{call_id}/status"


def build_media_stream_url(public_base_url: str) -> str:
    parsed = urlsplit(public_base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Twilio Media Streams require a public HTTPS base URL")
    path = f"{parsed.path.rstrip('/')}/media/twilio"
    return urlunsplit(("wss", parsed.netloc, path, "", ""))


def build_media_stream_twiml(public_base_url: str, call_id: UUID) -> str:
    response = VoiceResponse()
    connect = response.connect()
    stream = connect.stream(url=build_media_stream_url(public_base_url))
    stream.parameter(name="call_id", value=str(call_id))
    return str(response)


class TwilioWebhookVerifier:
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
        callback_url = build_status_callback_url(
            self.public_base_url,
            call_id,
        )
        return self.validator.validate(callback_url, parameters, signature)

    def validate_media_stream(self, *, signature: str) -> bool:
        return self.validator.validate(
            build_media_stream_url(self.public_base_url),
            {},
            signature,
        )


class TwilioTelephonyGateway:
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
