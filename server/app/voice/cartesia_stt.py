import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Protocol

from cartesia import AsyncCartesia

from app.voice.errors import VoiceRuntimeError
from app.voice.transcription import (
    StreamingTranscriber,
    TranscriptEvent,
    TranscriptHandler,
    TranscriptionError,
    TranscriptionSessionClosedError,
    TranscriptKind,
)


class _CartesiaConnection(Protocol):
    def __aiter__(self) -> AsyncIterator[object]: ...

    async def send_raw(self, data: bytes | str) -> None: ...

    async def send(self, event: dict[str, str]) -> None: ...

    async def close(self, *, code: int = 1000, reason: str = "") -> None: ...


def normalize_cartesia_event(event: object) -> TranscriptEvent | None:
    event_type = getattr(event, "type", None)

    if event_type == "error":
        message = getattr(event, "message", None) or "Cartesia STT error"
        raise TranscriptionError(str(message))

    if event_type not in {"turn.update", "turn.end"}:
        return None

    transcript = getattr(event, "transcript", None)
    if not isinstance(transcript, str) or not transcript.strip():
        return None

    kind = TranscriptKind.FINAL if event_type == "turn.end" else TranscriptKind.PARTIAL
    return TranscriptEvent(text=transcript, kind=kind)


class CartesiaStreamingTranscriber(StreamingTranscriber):
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
        if self._failure is not None:
            raise self._failure


class CartesiaSTTProvider:
    def __init__(self, client: AsyncCartesia) -> None:
        self._client = client

    async def open_session(
        self,
        *,
        on_transcript: TranscriptHandler,
    ) -> StreamingTranscriber:
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
