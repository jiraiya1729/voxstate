"""Provider-neutral speech-to-text contracts for the conversation runtime."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.voice.errors import VoiceRuntimeError


class TranscriptKind(StrEnum):
    """Provider-neutral transcript events consumed by the conversation session."""

    SPEECH_STARTED = "speech_started"
    PARTIAL = "partial"
    EAGER_END = "eager_end"
    RESUMED = "resumed"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    """One normalized STT event with optional transcript text."""

    text: str
    kind: TranscriptKind


TranscriptHandler = Callable[[TranscriptEvent], Awaitable[None]]


class TranscriptionError(VoiceRuntimeError):
    pass


class TranscriptionSessionClosedError(TranscriptionError):
    pass


class StreamingTranscriber(Protocol):
    """Active STT session that accepts audio and emits transcript callbacks."""

    async def send_audio(self, audio: bytes) -> None: ...

    async def close(self) -> bool: ...


class SpeechToTextProvider(Protocol):
    """Factory interface for opening provider-backed streaming transcription."""

    async def open_session(
        self,
        *,
        on_transcript: TranscriptHandler,
    ) -> StreamingTranscriber: ...
