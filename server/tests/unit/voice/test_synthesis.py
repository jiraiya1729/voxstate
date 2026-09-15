from collections.abc import Awaitable, Callable
from unittest.mock import Mock
from uuid import UUID

import pytest

import app.voice.conversation.synthesis as synthesis_module
from app.voice.conversation.synthesis import (
    SynthesisProviderError,
    SynthesizingResponseObserver,
)
from app.voice.conversation.turns import TurnMarker, TurnTiming

CALL_ID = UUID("00000000-0000-0000-0000-000000000001")


class FixedClock:
    def now(self) -> float:
        return 1.0


class ChunkingSynthesizer:
    async def synthesize(
        self,
        text: str,
        *,
        on_audio: Callable[[bytes], Awaitable[None]],
    ) -> None:
        assert text == "Hello there"
        await on_audio(b"one")
        await on_audio(b"two")


@pytest.mark.asyncio
async def test_tts_logs_request_and_audio_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Mock()
    monkeypatch.setattr(synthesis_module, "logger", logger)
    audio: list[bytes] = []

    async def capture(chunk: bytes) -> None:
        audio.append(chunk)

    observer = SynthesizingResponseObserver(
        call_id=CALL_ID,
        synthesizer=ChunkingSynthesizer(),
        audio_sink=capture,
    )
    timing = TurnTiming(turn_id=1, clock=FixedClock())
    await observer.on_response(CALL_ID, "Hello there", timing=timing)

    assert audio == [b"one", b"two"]
    messages = [call.args[0] for call in logger.info.call_args_list]
    debug_messages = [call.args[0] for call in logger.debug.call_args_list]
    assert "voice.tts.request call_id=%s chars=%d" in messages
    assert "voice.tts.text call_id=%s text=%r" in debug_messages
    assert (
        "voice.tts.complete call_id=%s elapsed_ms=%.1f chunks=%d audio_bytes=%d"
        in messages
    )
    complete = logger.info.call_args_list[-1]
    assert complete.args[1] == CALL_ID
    assert complete.args[3:] == (2, 6)
    snapshot = timing.snapshot()
    assert snapshot.timestamp(TurnMarker.TTS_START) == 1.0
    assert snapshot.timestamp(TurnMarker.TTS_FIRST_BYTE) == 1.0
    assert snapshot.timestamp(TurnMarker.FIRST_PLAYBACK) == 1.0


@pytest.mark.asyncio
async def test_tts_failure_is_logged_and_propagated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSynthesizer:
        async def synthesize(
            self,
            text: str,
            *,
            on_audio: Callable[[bytes], Awaitable[None]],
        ) -> None:
            raise SynthesisProviderError("failed")

    logger = Mock()
    monkeypatch.setattr(synthesis_module, "logger", logger)

    async def discard(chunk: bytes) -> None:
        del chunk

    observer = SynthesizingResponseObserver(
        call_id=CALL_ID,
        synthesizer=FailingSynthesizer(),
        audio_sink=discard,
    )

    with pytest.raises(SynthesisProviderError):
        await observer.on_response(
            CALL_ID,
            "Hello there",
            timing=TurnTiming(turn_id=1, clock=FixedClock()),
        )

    assert logger.exception.call_args.args[0] == (
        "voice.tts.error call_id=%s elapsed_ms=%.1f chunks=%d audio_bytes=%d"
    )
