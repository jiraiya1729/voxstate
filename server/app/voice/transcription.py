from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.voice.errors import VoiceRuntimeError


class TranscriptKind(StrEnum):
    PARTIAL = "partial"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    text: str
    kind: TranscriptKind


TranscriptHandler = Callable[[TranscriptEvent], Awaitable[None]]


class TranscriptionError(VoiceRuntimeError):
    pass


class TranscriptionSessionClosedError(TranscriptionError):
    pass


class StreamingTranscriber(Protocol):
    async def send_audio(self, audio: bytes) -> None: ...

    async def close(self) -> bool: ...


class SpeechToTextProvider(Protocol):
    async def open_session(
        self,
        *,
        on_transcript: TranscriptHandler,
    ) -> StreamingTranscriber: ...
