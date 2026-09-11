import json
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

import pytest

from app.calls.repository import CallRepository
from app.calls.service import CallLifecycleService, CallService
from app.calls.telephony import ProviderCall
from app.db.database import Database
from app.voice.media_messages import (
    MediaMessage,
    StartMessage,
    StopMessage,
    parse_media_message,
)
from app.voice.response import Message, MessageRole, ModelProviderError
from app.voice.sessions import ActiveCallRegistry, MediaSessionService
from app.voice.transcription import TranscriptEvent, TranscriptKind

PROVIDER_CALL_ID = "CA00000000000000000000000000000099"


class FakeTelephony:
    async def create_call(self, *, call_id: UUID, to_number: str) -> ProviderCall:
        del call_id, to_number
        return ProviderCall(PROVIDER_CALL_ID)


class FakeTranscriber:
    def __init__(self) -> None:
        self.audio: list[bytes] = []
        self.closed = False

    async def send_audio(self, audio: bytes) -> None:
        self.audio.append(audio)

    async def close(self) -> bool:
        self.closed = True
        return True


class FakeSTT:
    def __init__(self) -> None:
        self.handler: Callable[[TranscriptEvent], Awaitable[None]] | None = None
        self.transcriber = FakeTranscriber()

    async def open_session(
        self,
        *,
        on_transcript: Callable[[TranscriptEvent], Awaitable[None]],
    ) -> FakeTranscriber:
        self.handler = on_transcript
        return self.transcriber


class FakeModel:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.turns: list[tuple[Message, ...]] = []

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
    ) -> str:
        del system_prompt
        self.turns.append(tuple(messages))
        if self.fail:
            raise ModelProviderError("simulated Bedrock failure")
        return "Your appointment is confirmed."


class FakeTTS:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def synthesize(
        self,
        text: str,
        *,
        on_audio: Callable[[bytes], Awaitable[None]],
    ) -> None:
        self.texts.append(text)
        await on_audio(b"audio-one")
        await on_audio(b"audio-two")


def media_messages(call_id: UUID) -> tuple[StartMessage, MediaMessage, StopMessage]:
    start = parse_media_message(
        json.dumps(
            {
                "event": "start",
                "sequenceNumber": "1",
                "streamSid": "MZ0099",
                "start": {
                    "accountSid": "AC0099",
                    "streamSid": "MZ0099",
                    "callSid": PROVIDER_CALL_ID,
                    "tracks": ["inbound"],
                    "mediaFormat": {
                        "encoding": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "channels": 1,
                    },
                    "customParameters": {"call_id": str(call_id)},
                },
            }
        )
    )
    media = parse_media_message(
        '{"event":"media","sequenceNumber":"2","streamSid":"MZ0099",'
        '"media":{"track":"inbound","chunk":"1","timestamp":"0",'
        '"payload":"AQID"}}'
    )
    stop = parse_media_message(
        '{"event":"stop","sequenceNumber":"3","streamSid":"MZ0099",'
        f'"stop":{{"accountSid":"AC0099","callSid":"{PROVIDER_CALL_ID}"}}}}'
    )
    assert isinstance(start, StartMessage)
    assert isinstance(media, MediaMessage)
    assert isinstance(stop, StopMessage)
    return start, media, stop


@pytest.mark.asyncio
async def test_first_ai_phone_call_completes_through_fake_provider_stack(
    database: Database,
) -> None:
    initiated = await CallService(
        database=database,
        telephony=FakeTelephony(),
    ).initiate_call("+15555550199")
    lifecycle = CallLifecycleService(database=database)
    assert (
        await lifecycle.apply_status_callback(
            call_id=initiated.id,
            provider_call_id=PROVIDER_CALL_ID,
            provider_status="answered",
        )
        == "in-progress"
    )

    stt = FakeSTT()
    model = FakeModel()
    tts = FakeTTS()
    voice = MediaSessionService(
        database=database,
        registry=ActiveCallRegistry(),
        stt_provider=stt,
        language_model=model,
        speech_synthesizer=tts,
    )
    playback: list[bytes] = []

    async def capture_playback(audio: bytes) -> None:
        playback.append(audio)

    start, media, stop = media_messages(initiated.id)
    active = await voice.start(start, audio_sink=capture_playback)
    await voice.receive_media(media)
    assert stt.handler is not None
    await stt.handler(
        TranscriptEvent(
            text="Book my appointment",
            kind=TranscriptKind.FINAL,
        )
    )
    await voice.stop(stop)
    final_status = await lifecycle.apply_status_callback(
        call_id=initiated.id,
        provider_call_id=PROVIDER_CALL_ID,
        provider_status="completed",
    )

    assert stt.transcriber.audio == [b"\x01\x02\x03"]
    assert model.turns == [
        (Message(role=MessageRole.USER, text="Book my appointment"),)
    ]
    assert tts.texts == ["Your appointment is confirmed."]
    assert playback == [b"audio-one", b"audio-two"]
    assert active.conversation.history == (
        Message(role=MessageRole.USER, text="Book my appointment"),
        Message(
            role=MessageRole.ASSISTANT,
            text="Your appointment is confirmed.",
        ),
    )
    assert active.closed is True
    assert final_status == "completed"


@pytest.mark.asyncio
async def test_downstream_failure_is_not_reported_as_call_success(
    database: Database,
) -> None:
    initiated = await CallService(
        database=database,
        telephony=FakeTelephony(),
    ).initiate_call("+15555550198")
    lifecycle = CallLifecycleService(database=database)
    await lifecycle.apply_status_callback(
        call_id=initiated.id,
        provider_call_id=PROVIDER_CALL_ID,
        provider_status="answered",
    )
    stt = FakeSTT()
    voice = MediaSessionService(
        database=database,
        registry=ActiveCallRegistry(),
        stt_provider=stt,
        language_model=FakeModel(fail=True),
        speech_synthesizer=FakeTTS(),
    )
    start, _, _ = media_messages(initiated.id)

    async def discard_playback(audio: bytes) -> None:
        del audio

    await voice.start(start, audio_sink=discard_playback)
    assert stt.handler is not None
    with pytest.raises(ModelProviderError, match="simulated Bedrock failure"):
        await stt.handler(TranscriptEvent(text="hello", kind=TranscriptKind.FINAL))

    async with database.session() as session:
        stored = await CallRepository(session).get_by_id(initiated.id)
    assert stored is not None
    assert stored.status == "in-progress"
