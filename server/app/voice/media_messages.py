import base64
import binascii
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class ConnectedMessage(BaseModel):
    event: Literal["connected"]
    protocol: Literal["Call"]
    version: str


class MediaFormat(BaseModel):
    encoding: str
    sample_rate: int = Field(alias="sampleRate")
    channels: int


class StartDetails(BaseModel):
    account_sid: str = Field(alias="accountSid", min_length=1)
    stream_sid: str = Field(alias="streamSid", min_length=1)
    call_sid: str = Field(alias="callSid", min_length=1)
    tracks: list[str]
    media_format: MediaFormat = Field(alias="mediaFormat")
    custom_parameters: dict[str, str] = Field(alias="customParameters")


class StartMessage(BaseModel):
    event: Literal["start"]
    sequence_number: int = Field(alias="sequenceNumber", ge=1)
    stream_sid: str = Field(alias="streamSid", min_length=1)
    start: StartDetails


class MediaDetails(BaseModel):
    track: Literal["inbound"]
    chunk: int = Field(ge=1)
    timestamp: int = Field(ge=0)
    payload: str = Field(min_length=1)

    def decoded_audio(self) -> bytes:
        try:
            return base64.b64decode(self.payload, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise MalformedMediaMessage("invalid base64 media payload") from exc


class MediaMessage(BaseModel):
    event: Literal["media"]
    sequence_number: int = Field(alias="sequenceNumber", ge=1)
    stream_sid: str = Field(alias="streamSid", min_length=1)
    media: MediaDetails


class StopDetails(BaseModel):
    account_sid: str = Field(alias="accountSid", min_length=1)
    call_sid: str = Field(alias="callSid", min_length=1)


class StopMessage(BaseModel):
    event: Literal["stop"]
    sequence_number: int = Field(alias="sequenceNumber", ge=1)
    stream_sid: str = Field(alias="streamSid", min_length=1)
    stop: StopDetails


InboundMediaMessage = Annotated[
    ConnectedMessage | StartMessage | MediaMessage | StopMessage,
    Field(discriminator="event"),
]

MESSAGE_ADAPTER = TypeAdapter(InboundMediaMessage)


class MalformedMediaMessage(ValueError):
    pass


def parse_media_message(raw_message: str) -> InboundMediaMessage:
    try:
        return MESSAGE_ADAPTER.validate_json(raw_message)
    except ValidationError as exc:
        raise MalformedMediaMessage("invalid Twilio media message") from exc


def build_outbound_media_message(stream_sid: str, audio: bytes) -> dict[str, object]:
    if not stream_sid.strip():
        raise ValueError("stream_sid must not be empty")
    if not audio:
        raise ValueError("audio must not be empty")
    return {
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": base64.b64encode(audio).decode("ascii")},
    }
