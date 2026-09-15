"""Provider-neutral assistant-response-to-speech bridge.

This file sends assistant text through TTS, streams audio, and clears playback.
"""

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Protocol
from uuid import UUID

from app.voice.conversation.turns import TurnMarker, TurnTiming
from app.voice.errors import VoiceRuntimeError

logger = logging.getLogger("uvicorn.error")

AudioSink = Callable[[bytes], Awaitable[None]]
ClearSink = Callable[[], Awaitable[None]]
MarkSink = Callable[[str], Awaitable[None]]
GenerationGuard = Callable[[], bool]


class SynthesisError(VoiceRuntimeError):
    pass


class EmptySynthesisInputError(SynthesisError):
    pass


class SynthesisProviderError(SynthesisError):
    pass


class EmptySynthesisResponseError(SynthesisError):
    pass


class SpeechSynthesizer(Protocol):
    """Provider-neutral TTS interface that streams audio chunks to a sink."""

    async def synthesize(self, text: str, *, on_audio: AudioSink) -> None: ...


class SynthesizingResponseObserver:
    """Turns assistant text into Twilio audio and handles interruption clears."""

    def __init__(
        self,
        *,
        call_id: UUID,
        synthesizer: SpeechSynthesizer,
        audio_sink: AudioSink,
        clear_sink: ClearSink | None = None,
        mark_sink: MarkSink | None = None,
    ) -> None:
        self.call_id = call_id
        self.synthesizer = synthesizer
        self.audio_sink = audio_sink
        self.clear_sink = clear_sink
        self.mark_sink = mark_sink

    async def on_response(
        self,
        call_id: UUID,
        text: str,
        *,
        timing: TurnTiming,
        generation: int = 0,
        is_current: GenerationGuard | None = None,
    ) -> str | None:
        """Synthesize one assistant response and optionally send a playback mark."""
        if call_id != self.call_id:
            raise SynthesisError("assistant response belongs to another call")

        logger.info(
            "voice.tts.request call_id=%s chars=%d",
            call_id,
            len(text),
        )
        logger.debug(
            "voice.tts.text call_id=%s text=%r",
            call_id,
            text,
        )
        started_at = perf_counter()
        timing.record(TurnMarker.TTS_START)
        chunk_count = 0
        audio_bytes = 0
        generation_is_current = is_current or (lambda: True)

        async def observed_audio_sink(audio: bytes) -> None:
            nonlocal chunk_count, audio_bytes
            if not generation_is_current():
                return
            timing.record(TurnMarker.TTS_FIRST_BYTE)
            chunk_count += 1
            audio_bytes += len(audio)
            logger.debug(
                "voice.tts.chunk call_id=%s chunk=%d audio_bytes=%d",
                call_id,
                chunk_count,
                len(audio),
            )
            await self.audio_sink(audio)
            timing.record(TurnMarker.FIRST_PLAYBACK)

        try:
            await self.synthesizer.synthesize(
                text,
                on_audio=observed_audio_sink,
            )
        except Exception:
            logger.exception(
                "voice.tts.error call_id=%s elapsed_ms=%.1f chunks=%d audio_bytes=%d",
                call_id,
                (perf_counter() - started_at) * 1000,
                chunk_count,
                audio_bytes,
            )
            raise

        logger.info(
            "voice.tts.complete call_id=%s elapsed_ms=%.1f chunks=%d audio_bytes=%d",
            call_id,
            (perf_counter() - started_at) * 1000,
            chunk_count,
            audio_bytes,
        )
        if not generation_is_current() or self.mark_sink is None:
            return None

        mark_name = f"turn-{generation}"
        await self.mark_sink(mark_name)
        return mark_name

    async def interrupt(self, call_id: UUID) -> bool:
        """Clear queued provider audio for the current call during barge-in/close."""
        if call_id != self.call_id:
            raise SynthesisError("interruption belongs to another call")
        if self.clear_sink is None:
            return False
        await self.clear_sink()
        return True
