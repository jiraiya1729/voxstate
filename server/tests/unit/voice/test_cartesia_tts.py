import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from app.voice.cartesia_tts import CartesiaSpeechSynthesizer
from app.voice.synthesis import (
    EmptySynthesisInputError,
    EmptySynthesisResponseError,
    SynthesisProviderError,
)


class FakeContext:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.pushed: list[str] = []
        self.finished = False
        self.cancelled = False

    async def push(self, text: str) -> None:
        self.pushed.append(text)

    async def no_more_inputs(self) -> None:
        self.finished = True

    async def receive(self) -> AsyncIterator[object]:
        for response in self.responses:
            await asyncio.sleep(0)
            yield response

    async def cancel(self) -> None:
        self.cancelled = True


class FakeConnection:
    def __init__(self, context: FakeContext) -> None:
        self.tts_context = context
        self.context_options: dict[str, object] = {}
        self.closed = False

    def context(self, **kwargs: object) -> FakeContext:
        self.context_options = kwargs
        return self.tts_context

    async def close(self) -> None:
        self.closed = True


class FakeConnectionManager:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def enter(self) -> FakeConnection:
        return self.connection


class FakeTTSResource:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def websocket_connect(self) -> FakeConnectionManager:
        return FakeConnectionManager(self.connection)


class FakeClient:
    def __init__(self, connection: FakeConnection) -> None:
        self.tts = FakeTTSResource(connection)


def make_synthesizer(
    responses: list[object],
) -> tuple[CartesiaSpeechSynthesizer, FakeConnection, FakeContext]:
    context = FakeContext(responses)
    connection = FakeConnection(context)
    synthesizer = CartesiaSpeechSynthesizer(
        client=FakeClient(connection),  # type: ignore[arg-type]
        voice_id="voice-123",
    )
    return synthesizer, connection, context


@pytest.mark.asyncio
async def test_synthesis_streams_mulaw_chunks() -> None:
    synthesizer, connection, context = make_synthesizer(
        [
            SimpleNamespace(type="chunk", audio=b"one"),
            SimpleNamespace(type="done"),
            SimpleNamespace(type="chunk", audio=b"two"),
        ]
    )
    audio: list[bytes] = []

    async def capture(chunk: bytes) -> None:
        audio.append(chunk)

    await synthesizer.synthesize(" Hello ", on_audio=capture)

    assert context.pushed == ["Hello"]
    assert context.finished is True
    assert connection.context_options == {
        "model_id": "sonic-latest",
        "voice": "voice-123",
        "output_format": {
            "container": "raw",
            "encoding": "pcm_mulaw",
            "sample_rate": 8000,
        },
        "language": "en",
        "timeout": 20.0,
    }
    assert audio == [b"one", b"two"]
    assert connection.closed is True


@pytest.mark.asyncio
async def test_empty_synthesis_input_is_rejected() -> None:
    synthesizer, _, _ = make_synthesizer([])

    with pytest.raises(EmptySynthesisInputError):
        await synthesizer.synthesize("  ", on_audio=lambda chunk: None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_provider_error_is_normalized() -> None:
    synthesizer, connection, _ = make_synthesizer(
        [SimpleNamespace(type="error", message="quota exceeded")]
    )

    async def discard(chunk: bytes) -> None:
        del chunk

    with pytest.raises(SynthesisProviderError, match="quota exceeded"):
        await synthesizer.synthesize("hello", on_audio=discard)

    assert connection.closed is True


@pytest.mark.asyncio
async def test_empty_provider_response_is_rejected() -> None:
    synthesizer, _, _ = make_synthesizer([SimpleNamespace(type="done")])

    async def discard(chunk: bytes) -> None:
        del chunk

    with pytest.raises(EmptySynthesisResponseError):
        await synthesizer.synthesize("hello", on_audio=discard)


@pytest.mark.asyncio
async def test_cancellation_cancels_context_and_closes_connection() -> None:
    started = asyncio.Event()

    class BlockingContext(FakeContext):
        async def receive(self) -> AsyncIterator[object]:
            started.set()
            await asyncio.Event().wait()
            if False:
                yield SimpleNamespace(type="done")

    context = BlockingContext([])
    connection = FakeConnection(context)
    synthesizer = CartesiaSpeechSynthesizer(
        client=FakeClient(connection),  # type: ignore[arg-type]
        voice_id="voice-123",
    )

    async def discard(chunk: bytes) -> None:
        del chunk

    task = asyncio.create_task(synthesizer.synthesize("hello", on_audio=discard))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert context.cancelled is True
    assert connection.closed is True
