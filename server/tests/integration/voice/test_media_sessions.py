import json
from collections.abc import Awaitable, Callable, Sequence
from unittest.mock import Mock

import pytest

import app.voice.sessions as sessions_module
from app.calls.repository import CallRepository
from app.db.database import Database
from app.voice.media_messages import (
    MediaMessage,
    StartMessage,
    StopMessage,
    parse_media_message,
)
from app.voice.response import Message, MessageRole
from app.voice.sessions import (
    ActiveCallRegistry,
    DuplicateMediaSessionError,
    MediaSessionService,
    UnknownMediaCallError,
)
from app.voice.transcription import TranscriptEvent, TranscriptKind


class FakeTranscriber:
    def __init__(self) -> None:
        self.audio: list[bytes] = []
        self.closed = False

    async def send_audio(self, audio: bytes) -> None:
        self.audio.append(audio)

    async def close(self) -> bool:
        if self.closed:
            return False
        self.closed = True
        return True


class FakeSTTProvider:
    def __init__(self) -> None:
        self.handlers: list[Callable[[TranscriptEvent], Awaitable[None]]] = []
        self.sessions: list[FakeTranscriber] = []

    async def open_session(
        self,
        *,
        on_transcript: Callable[[TranscriptEvent], Awaitable[None]],
    ) -> FakeTranscriber:
        session = FakeTranscriber()
        self.handlers.append(on_transcript)
        self.sessions.append(session)
        return session


class FakeLanguageModel:
    def __init__(self) -> None:
        self.messages: list[tuple[Message, ...]] = []

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
    ) -> str:
        self.messages.append(tuple(messages))
        return "How can I help?"


class FakeSpeechSynthesizer:
    def __init__(self) -> None:
        self.requests: list[str] = []

    async def synthesize(
        self,
        text: str,
        *,
        on_audio: Callable[[bytes], Awaitable[None]],
    ) -> None:
        self.requests.append(text)
        await on_audio(b"assistant-audio")


async def discard_audio(audio: bytes) -> None:
    del audio


def start_payload(call_id: str, call_sid: str = "CA0001") -> StartMessage:
    message = parse_media_message(
        json.dumps(
            {
                "event": "start",
                "sequenceNumber": "1",
                "streamSid": "MZ0001",
                "start": {
                    "accountSid": "AC0001",
                    "streamSid": "MZ0001",
                    "callSid": call_sid,
                    "tracks": ["inbound"],
                    "mediaFormat": {
                        "encoding": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "channels": 1,
                    },
                    "customParameters": {"call_id": call_id},
                },
            }
        )
    )
    assert isinstance(message, StartMessage)
    return message


def make_service(
    database: Database,
) -> tuple[
    MediaSessionService,
    FakeSTTProvider,
    FakeLanguageModel,
    FakeSpeechSynthesizer,
]:
    stt_provider = FakeSTTProvider()
    language_model = FakeLanguageModel()
    synthesizer = FakeSpeechSynthesizer()
    service = MediaSessionService(
        database=database,
        registry=ActiveCallRegistry(),
        stt_provider=stt_provider,
        language_model=language_model,
        speech_synthesizer=synthesizer,
    )
    return service, stt_provider, language_model, synthesizer


@pytest.mark.asyncio
async def test_session_streams_media_and_normalized_transcripts(
    database: Database,
) -> None:
    async with database.session() as session:
        call = await CallRepository(session).create(to_phone_number="+15555550130")
        await CallRepository(session).mark_provider_accepted(
            call_id=call.id,
            provider_call_id="CA0001",
        )

    service, stt_provider, language_model, synthesizer = make_service(database)
    outbound_audio: list[bytes] = []

    async def capture_audio(audio: bytes) -> None:
        outbound_audio.append(audio)

    active = await service.start(
        start_payload(str(call.id)),
        audio_sink=capture_audio,
    )
    media = parse_media_message(
        '{"event":"media","sequenceNumber":"2",'
        '"streamSid":"MZ0001","media":{"track":"inbound",'
        '"chunk":"1","timestamp":"0","payload":"AQID"}}'
    )
    assert isinstance(media, MediaMessage)

    await service.receive_media(media)
    await stt_provider.handlers[0](
        TranscriptEvent(text="hello", kind=TranscriptKind.PARTIAL)
    )
    await stt_provider.handlers[0](
        TranscriptEvent(text="hello there", kind=TranscriptKind.FINAL)
    )

    assert active.call_id == call.id
    assert active.media_frames_received == 1
    assert active.media_bytes_received == 3
    assert stt_provider.sessions[0].audio == [b"\x01\x02\x03"]
    assert language_model.messages == [
        (Message(role=MessageRole.USER, text="hello there"),)
    ]
    assert synthesizer.requests == ["How can I help?"]
    assert outbound_audio == [b"assistant-audio"]


@pytest.mark.asyncio
async def test_unknown_call_does_not_open_stt_session(database: Database) -> None:
    service, stt_provider, _, _ = make_service(database)

    with pytest.raises(UnknownMediaCallError):
        await service.start(
            start_payload("00000000-0000-0000-0000-000000000999"),
            audio_sink=discard_audio,
        )

    assert stt_provider.sessions == []


@pytest.mark.asyncio
async def test_duplicate_registration_closes_unused_stt_session(
    database: Database,
) -> None:
    async with database.session() as session:
        call = await CallRepository(session).create(to_phone_number="+15555550131")
        await CallRepository(session).mark_provider_accepted(
            call_id=call.id,
            provider_call_id="CA0001",
        )

    service, stt_provider, _, _ = make_service(database)
    message = start_payload(str(call.id))
    await service.start(message, audio_sink=discard_audio)

    with pytest.raises(DuplicateMediaSessionError):
        await service.start(message, audio_sink=discard_audio)

    assert len(stt_provider.sessions) == 2
    assert stt_provider.sessions[0].closed is False
    assert stt_provider.sessions[1].closed is True


@pytest.mark.asyncio
async def test_stop_and_disconnect_close_stt_once(database: Database) -> None:
    async with database.session() as session:
        call = await CallRepository(session).create(to_phone_number="+15555550132")
        await CallRepository(session).mark_provider_accepted(
            call_id=call.id,
            provider_call_id="CA0001",
        )

    service, stt_provider, _, _ = make_service(database)
    active = await service.start(
        start_payload(str(call.id)),
        audio_sink=discard_audio,
    )
    stop = parse_media_message(
        '{"event":"stop","sequenceNumber":"3",'
        '"streamSid":"MZ0001","stop":{'
        '"accountSid":"AC0001","callSid":"CA0001"}}'
    )
    assert isinstance(stop, StopMessage)

    assert await service.stop(stop) is True
    assert await service.disconnect(active.stream_sid) is False
    assert active.closed is True
    assert stt_provider.sessions[0].closed is True


@pytest.mark.asyncio
async def test_session_start_and_stop_are_logged(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Mock()
    monkeypatch.setattr(sessions_module, "logger", logger)
    async with database.session() as session:
        call = await CallRepository(session).create(to_phone_number="+15555550133")
        await CallRepository(session).mark_provider_accepted(
            call_id=call.id,
            provider_call_id="CA0001",
        )

    service, _, _, _ = make_service(database)
    await service.start(start_payload(str(call.id)), audio_sink=discard_audio)
    stop = parse_media_message(
        '{"event":"stop","sequenceNumber":"3",'
        '"streamSid":"MZ0001","stop":{'
        '"accountSid":"AC0001","callSid":"CA0001"}}'
    )
    assert isinstance(stop, StopMessage)
    await service.stop(stop)

    messages = [call.args[0] for call in logger.info.call_args_list]
    assert (
        "voice.session.started call_id=%s provider_call_id=%s stream_sid=%s" in messages
    )
    assert (
        "voice.session.stopped call_id=%s stream_sid=%s frames=%d audio_bytes=%d"
        in messages
    )
