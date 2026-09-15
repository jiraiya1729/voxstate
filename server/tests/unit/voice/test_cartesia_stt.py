import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from app.voice.conversation.transcription import (
    TranscriptEvent,
    TranscriptionError,
    TranscriptKind,
)
from app.voice.providers.cartesia_stt import (
    CartesiaStreamingTranscriber,
    CartesiaSTTProvider,
    normalize_cartesia_event,
)


class FakeConnection:
    def __init__(self) -> None:
        self.events: asyncio.Queue[object | None] = asyncio.Queue()
        self.audio: list[bytes | str] = []
        self.commands: list[dict[str, str]] = []
        self.closed = False

    def __aiter__(self) -> AsyncIterator[object]:
        return self

    async def __anext__(self) -> object:
        event = await self.events.get()
        if event is None:
            raise StopAsyncIteration
        return event

    async def send_raw(self, data: bytes | str) -> None:
        self.audio.append(data)

    async def send(self, event: dict[str, str]) -> None:
        self.commands.append(event)
        if event == {"type": "close"}:
            await self.events.put(None)

    async def close(self, *, code: int = 1000, reason: str = "") -> None:
        self.closed = True


def test_cartesia_events_are_normalized() -> None:
    assert normalize_cartesia_event(
        SimpleNamespace(type="turn.start")
    ) == TranscriptEvent(text="", kind=TranscriptKind.SPEECH_STARTED)
    assert normalize_cartesia_event(
        SimpleNamespace(type="turn.update", transcript="hello")
    ) == TranscriptEvent(text="hello", kind=TranscriptKind.PARTIAL)
    assert normalize_cartesia_event(
        SimpleNamespace(type="turn.eager_end", transcript="hello maybe")
    ) == TranscriptEvent(text="hello maybe", kind=TranscriptKind.EAGER_END)
    assert normalize_cartesia_event(
        SimpleNamespace(type="turn.resume")
    ) == TranscriptEvent(text="", kind=TranscriptKind.RESUMED)
    assert normalize_cartesia_event(
        SimpleNamespace(type="turn.end", transcript="hello there")
    ) == TranscriptEvent(text="hello there", kind=TranscriptKind.FINAL)


@pytest.mark.parametrize(
    "event",
    [
        SimpleNamespace(type="connected"),
        SimpleNamespace(type="turn.update", transcript="   "),
        SimpleNamespace(type="turn.eager_end", transcript=""),
        SimpleNamespace(type="turn.end", transcript=""),
    ],
)
def test_non_transcript_and_empty_events_are_ignored(event: object) -> None:
    assert normalize_cartesia_event(event) is None


def test_cartesia_error_event_is_raised() -> None:
    with pytest.raises(TranscriptionError, match="provider unavailable"):
        normalize_cartesia_event(
            SimpleNamespace(type="error", message="provider unavailable")
        )


@pytest.mark.asyncio
async def test_stream_forwards_audio_and_transcripts_then_closes() -> None:
    connection = FakeConnection()
    transcripts: list[TranscriptEvent] = []

    async def record(event: TranscriptEvent) -> None:
        transcripts.append(event)

    stream = CartesiaStreamingTranscriber(
        connection=connection,
        on_transcript=record,
    )
    await stream.send_audio(b"\xff\x7f")
    await connection.events.put(SimpleNamespace(type="turn.start"))
    await connection.events.put(SimpleNamespace(type="turn.update", transcript="hi"))
    await connection.events.put(SimpleNamespace(type="turn.eager_end", transcript="hi"))
    await connection.events.put(SimpleNamespace(type="turn.resume"))
    await connection.events.put(SimpleNamespace(type="turn.end", transcript="hi there"))
    await asyncio.sleep(0)

    assert await stream.close() is True
    assert await stream.close() is False
    assert connection.audio == [b"\xff\x7f"]
    assert connection.commands == [{"type": "close"}]
    assert connection.closed is True
    assert transcripts == [
        TranscriptEvent(text="", kind=TranscriptKind.SPEECH_STARTED),
        TranscriptEvent(text="hi", kind=TranscriptKind.PARTIAL),
        TranscriptEvent(text="hi", kind=TranscriptKind.EAGER_END),
        TranscriptEvent(text="", kind=TranscriptKind.RESUMED),
        TranscriptEvent(text="hi there", kind=TranscriptKind.FINAL),
    ]


@pytest.mark.asyncio
async def test_provider_error_is_exposed_on_audio_path() -> None:
    connection = FakeConnection()

    async def ignore(event: TranscriptEvent) -> None:
        pass

    stream = CartesiaStreamingTranscriber(
        connection=connection,
        on_transcript=ignore,
    )
    await connection.events.put(SimpleNamespace(type="error", message="quota exceeded"))
    await asyncio.sleep(0)

    with pytest.raises(TranscriptionError, match="quota exceeded"):
        await stream.send_audio(b"next frame")

    await stream.close()


@pytest.mark.asyncio
async def test_close_cancels_an_active_transcript_handler() -> None:
    connection = FakeConnection()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def block_response(event: TranscriptEvent) -> None:
        del event
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    stream = CartesiaStreamingTranscriber(
        connection=connection,
        on_transcript=block_response,
    )
    await connection.events.put(SimpleNamespace(type="turn.end", transcript="hello"))
    await asyncio.wait_for(started.wait(), timeout=1)

    await stream.close()

    assert cancelled.is_set()
    assert connection.closed is True


@pytest.mark.asyncio
async def test_provider_opens_ink2_for_twilio_audio() -> None:
    connection = FakeConnection()
    captured: dict[str, Any] = {}

    class FakeManager:
        async def enter(self) -> FakeConnection:
            return connection

    class FakeAutoFinalize:
        def websocket(self, **kwargs: Any) -> FakeManager:
            captured.update(kwargs)
            return FakeManager()

    fake_client = SimpleNamespace(stt=SimpleNamespace(auto_finalize=FakeAutoFinalize()))

    async def ignore(event: TranscriptEvent) -> None:
        pass

    provider = CartesiaSTTProvider(fake_client)
    stream = await provider.open_session(on_transcript=ignore)

    assert captured == {
        "encoding": "pcm_mulaw",
        "model": "ink-2",
        "sample_rate": 8000,
    }

    await stream.close()
