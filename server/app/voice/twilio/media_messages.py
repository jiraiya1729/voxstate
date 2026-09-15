"""Typed Twilio media WebSocket message models and outbound frame builders."""

import base64
import binascii
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class ConnectedMessage(BaseModel):
    """Twilio media WebSocket connected frame."""

    event: Literal["connected"]
    protocol: Literal["Call"]
    version: str


class MediaFormat(BaseModel):
    """Audio format announced by Twilio when a media stream starts."""

    encoding: str
    sample_rate: int = Field(alias="sampleRate")
    channels: int


class StartDetails(BaseModel):
    """Twilio stream metadata used to bind media to a persisted call."""

    account_sid: str = Field(alias="accountSid", min_length=1)
    stream_sid: str = Field(alias="streamSid", min_length=1)
    call_sid: str = Field(alias="callSid", min_length=1)
    tracks: list[str]
    media_format: MediaFormat = Field(alias="mediaFormat")
    custom_parameters: dict[str, str] = Field(alias="customParameters")


class StartMessage(BaseModel):
    """Twilio media start frame carrying call, stream, and custom parameters."""

    event: Literal["start"]
    sequence_number: int = Field(alias="sequenceNumber", ge=1)
    stream_sid: str = Field(alias="streamSid", min_length=1)
    start: StartDetails


class MediaDetails(BaseModel):
    """Inbound Twilio audio payload and its stream ordering metadata."""

    track: Literal["inbound"]
    chunk: int = Field(ge=1)
    timestamp: int = Field(ge=0)
    payload: str = Field(min_length=1)

    def decoded_audio(self) -> bytes:
        """Decode the base64 Twilio payload into raw audio bytes for STT."""
        try:
            return base64.b64decode(self.payload, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise MalformedMediaMessage("invalid base64 media payload") from exc


class MediaMessage(BaseModel):
    """Twilio inbound audio frame normalized into a typed model."""

    event: Literal["media"]
    sequence_number: int = Field(alias="sequenceNumber", ge=1)
    stream_sid: str = Field(alias="streamSid", min_length=1)
    media: MediaDetails


class StopDetails(BaseModel):
    """Twilio stop metadata used to close the matching active stream."""

    account_sid: str = Field(alias="accountSid", min_length=1)
    call_sid: str = Field(alias="callSid", min_length=1)


class StopMessage(BaseModel):
    """Twilio media stop frame."""

    event: Literal["stop"]
    sequence_number: int = Field(alias="sequenceNumber", ge=1)
    stream_sid: str = Field(alias="streamSid", min_length=1)
    stop: StopDetails


class MarkDetails(BaseModel):
    """Twilio playback mark acknowledging queued outbound audio."""

    name: str = Field(min_length=1)


class MarkMessage(BaseModel):
    """Twilio media mark frame used to detect playback completion."""

    event: Literal["mark"]
    sequence_number: int = Field(alias="sequenceNumber", ge=1)
    stream_sid: str = Field(alias="streamSid", min_length=1)
    mark: MarkDetails


InboundMediaMessage = Annotated[
    ConnectedMessage | StartMessage | MediaMessage | StopMessage | MarkMessage,
    Field(discriminator="event"),
]

MESSAGE_ADAPTER = TypeAdapter(InboundMediaMessage)


class MalformedMediaMessage(ValueError):
    pass


def parse_media_message(raw_message: str) -> InboundMediaMessage:
    """Parse one raw Twilio WebSocket message into a typed internal frame."""
    try:
        return MESSAGE_ADAPTER.validate_json(raw_message)
    except ValidationError as exc:
        raise MalformedMediaMessage("invalid Twilio media message") from exc


def build_outbound_media_message(stream_sid: str, audio: bytes) -> dict[str, object]:
    """Build a Twilio outbound media frame from synthesized audio bytes."""
    if not stream_sid.strip():
        raise ValueError("stream_sid must not be empty")
    if not audio:
        raise ValueError("audio must not be empty")
    return {
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": base64.b64encode(audio).decode("ascii")},
    }


def build_outbound_clear_message(stream_sid: str) -> dict[str, str]:
    """Build a Twilio clear command that drops queued playback audio."""
    if not stream_sid.strip():
        raise ValueError("stream_sid must not be empty")
    return {"event": "clear", "streamSid": stream_sid}


def build_outbound_mark_message(stream_sid: str, name: str) -> dict[str, object]:
    """Build a Twilio mark command used to observe playback completion."""
    if not stream_sid.strip():
        raise ValueError("stream_sid must not be empty")
    if not name.strip():
        raise ValueError("mark name must not be empty")
    return {"event": "mark", "streamSid": stream_sid, "mark": {"name": name}}
