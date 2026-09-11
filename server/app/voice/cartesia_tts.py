import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Protocol

from cartesia import AsyncCartesia

from app.voice.synthesis import (
    AudioSink,
    EmptySynthesisInputError,
    EmptySynthesisResponseError,
    SynthesisError,
    SynthesisProviderError,
)


class _TTSContext(Protocol):
    async def push(self, text: str) -> None: ...

    async def no_more_inputs(self) -> None: ...

    def receive(self) -> AsyncIterator[object]: ...

    async def cancel(self) -> None: ...


class _TTSConnection(Protocol):
    def context(self, **kwargs: object) -> _TTSContext: ...

    async def close(self) -> None: ...


class CartesiaSpeechSynthesizer:
    def __init__(
        self,
        *,
        client: AsyncCartesia,
        voice_id: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._client = client
        self._voice_id = voice_id
        self._timeout_seconds = timeout_seconds

    async def synthesize(self, text: str, *, on_audio: AudioSink) -> None:
        text = text.strip()
        if not text:
            raise EmptySynthesisInputError("speech text must not be empty")

        connection: _TTSConnection | None = None
        context: _TTSContext | None = None
        try:
            connection = await self._client.tts.websocket_connect().enter()
            context = connection.context(
                model_id="sonic-latest",
                voice=self._voice_id,
                output_format={
                    "container": "raw",
                    "encoding": "pcm_mulaw",
                    "sample_rate": 8000,
                },
                language="en",
                timeout=self._timeout_seconds,
            )
            await context.push(text)
            await context.no_more_inputs()

            received_audio = False
            async for response in context.receive():
                response_type = getattr(response, "type", None)
                if response_type == "chunk":
                    audio = getattr(response, "audio", None)
                    if isinstance(audio, bytes) and audio:
                        received_audio = True
                        await on_audio(audio)
                elif response_type == "error":
                    message = getattr(response, "message", None)
                    raise SynthesisProviderError(
                        str(message or "Cartesia TTS returned an error")
                    )

            if not received_audio:
                raise EmptySynthesisResponseError("Cartesia TTS returned no audio")
        except asyncio.CancelledError:
            if context is not None:
                with suppress(Exception):
                    await context.cancel()
            raise
        except SynthesisError:
            raise
        except Exception as exc:
            raise SynthesisProviderError("Cartesia TTS request failed") from exc
        finally:
            if connection is not None:
                with suppress(Exception):
                    await connection.close()
