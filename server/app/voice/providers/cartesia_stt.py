"""Cartesia streaming speech-to-text adapter.

This file opens Cartesia STT, forwards Twilio audio, and normalizes events.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Protocol

from cartesia import AsyncCartesia

from app.voice.conversation.transcription import (
    StreamingTranscriber,
    TranscriptEvent,
    TranscriptHandler,
    TranscriptionError,
    TranscriptionSessionClosedError,
    TranscriptKind,
)
from app.voice.errors import VoiceRuntimeError


class _CartesiaConnection(Protocol):
    """Subset of Cartesia's STT WebSocket connection used by the adapter."""

    def __aiter__(self) -> AsyncIterator[object]: ...

    async def send_raw(self, data: bytes | str) -> None: ...

    async def send(self, event: dict[str, str]) -> None: ...

    async def close(self, *, code: int = 1000, reason: str = "") -> None: ...


def normalize_cartesia_event(event: object) -> TranscriptEvent | None:
    """Translate Cartesia STT events into Voxstate transcript events."""
    event_type = getattr(event, "type", None)

    if event_type == "error":
        message = getattr(event, "message", None) or "Cartesia STT error"
        raise TranscriptionError(str(message))

    if event_type == "turn.start":
        return TranscriptEvent(text="", kind=TranscriptKind.SPEECH_STARTED)

    if event_type == "turn.resume":
        return TranscriptEvent(text="", kind=TranscriptKind.RESUMED)

    transcript_kinds = {
        "turn.update": TranscriptKind.PARTIAL,
        "turn.eager_end": TranscriptKind.EAGER_END,
        "turn.end": TranscriptKind.FINAL,
    }
    kind = transcript_kinds.get(event_type)
    if kind is None:
        return None

    transcript = getattr(event, "transcript", None)
    if not isinstance(transcript, str) or not transcript.strip():
        return None

    return TranscriptEvent(text=transcript, kind=kind)


class CartesiaStreamingTranscriber(StreamingTranscriber):
    """Active Cartesia STT stream that forwards audio and receives transcript events."""

    def __init__(
        self,
        *,
        connection: _CartesiaConnection,
        on_transcript: TranscriptHandler,
    ) -> None:
        self._connection = connection
        self._on_transcript = on_transcript
        self._closed = False
        self._failure: VoiceRuntimeError | None = None
        self._close_lock = asyncio.Lock()
        self._reader_task = asyncio.create_task(self._receive_events())

    async def send_audio(self, audio: bytes) -> None:
        """Send one Twilio audio frame to Cartesia unless the STT session failed."""
        if self._closed:
            raise TranscriptionSessionClosedError("STT session is closed")
        self._raise_if_failed()
        if not audio:
            return

        try:
            await self._connection.send_raw(audio)
        except Exception as exc:
            raise TranscriptionError("failed to send audio to Cartesia STT") from exc

        self._raise_if_failed()

    async def close(self) -> bool:
        """Close the STT stream once and stop its background reader task."""
        async with self._close_lock:
            if self._closed:
                return False
            self._closed = True

            if self._failure is None:
                with suppress(Exception):
                    await self._connection.send({"type": "close"})

            if not self._reader_task.done():
                self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)
            with suppress(Exception):
                await self._connection.close()

            return True

    async def _receive_events(self) -> None:
        """Background task that converts provider events into transcript callbacks."""
        try:
            async for provider_event in self._connection:
                event = normalize_cartesia_event(provider_event)
                if event is not None:
                    await self._on_transcript(event)
        except asyncio.CancelledError:
            raise
        except VoiceRuntimeError as exc:
            self._failure = exc
        except Exception as exc:
            self._failure = TranscriptionError("Cartesia STT receive loop failed")
            self._failure.__cause__ = exc
        else:
            if not self._closed:
                self._failure = TranscriptionError(
                    "Cartesia STT connection closed unexpectedly"
                )

    def _raise_if_failed(self) -> None:
        """Surface asynchronous STT reader failures on the audio send path."""
        if self._failure is not None:
            raise self._failure


class CartesiaSTTProvider:
    """Factory for Cartesia streaming STT sessions configured for Twilio audio."""

    def __init__(self, client: AsyncCartesia) -> None:
        self._client = client

    async def open_session(
        self,
        *,
        on_transcript: TranscriptHandler,
    ) -> StreamingTranscriber:
        """Open a Cartesia STT WebSocket and attach Voxstate's transcript handler."""
        try:
            connection = await self._client.stt.auto_finalize.websocket(
                encoding="pcm_mulaw",
                model="ink-2",
                sample_rate=8000,
            ).enter()
        except Exception as exc:
            raise TranscriptionError("failed to open Cartesia STT session") from exc

        return CartesiaStreamingTranscriber(
            connection=connection,
            on_transcript=on_transcript,
        )
