from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from app.voice.errors import VoiceRuntimeError

AudioSink = Callable[[bytes], Awaitable[None]]


class SynthesisError(VoiceRuntimeError):
    pass


class EmptySynthesisInputError(SynthesisError):
    pass


class SynthesisProviderError(SynthesisError):
    pass


class EmptySynthesisResponseError(SynthesisError):
    pass


class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str, *, on_audio: AudioSink) -> None: ...


class SynthesizingResponseObserver:
    def __init__(
        self,
        *,
        call_id: UUID,
        synthesizer: SpeechSynthesizer,
        audio_sink: AudioSink,
    ) -> None:
        self.call_id = call_id
        self.synthesizer = synthesizer
        self.audio_sink = audio_sink

    async def on_response(self, call_id: UUID, text: str) -> None:
        if call_id != self.call_id:
            raise SynthesisError("assistant response belongs to another call")
        await self.synthesizer.synthesize(text, on_audio=self.audio_sink)
