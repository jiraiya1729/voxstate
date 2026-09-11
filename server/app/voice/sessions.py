import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import UUID

from app.calls.lifecycle import (
    TERMINAL_STATUSES,
    CallStatus,
    ProviderCallMismatchError,
)
from app.calls.repository import CallRepository
from app.db.database import Database
from app.voice.media_messages import MediaMessage, StartMessage, StopMessage
from app.voice.response import (
    ConversationSession,
    LanguageModel,
)
from app.voice.synthesis import (
    AudioSink,
    SpeechSynthesizer,
    SynthesizingResponseObserver,
)
from app.voice.transcription import SpeechToTextProvider, StreamingTranscriber


class MediaSessionError(Exception):
    pass


class UnknownMediaCallError(MediaSessionError):
    pass


class InvalidMediaStartError(MediaSessionError):
    pass


class UnknownMediaStreamError(MediaSessionError):
    pass


class DuplicateMediaSessionError(MediaSessionError):
    pass


@dataclass
class ActiveCallSession:
    call_id: UUID
    provider_call_id: str
    stream_sid: str
    transcriber: StreamingTranscriber
    conversation: ConversationSession
    media_frames_received: int = 0
    media_bytes_received: int = 0
    closed: bool = False
    _close_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def receive_audio(self, audio: bytes) -> None:
        if self.closed:
            raise UnknownMediaStreamError(self.stream_sid)
        await self.transcriber.send_audio(audio)
        self.media_frames_received += 1
        self.media_bytes_received += len(audio)

    async def close(self) -> bool:
        async with self._close_lock:
            if self.closed:
                return False
            self.closed = True
            await self.transcriber.close()
            return True


class ActiveCallRegistry:
    def __init__(self) -> None:
        self._by_stream: dict[str, ActiveCallSession] = {}
        self._stream_by_call: dict[UUID, str] = {}
        self._lock = asyncio.Lock()

    async def register(self, session: ActiveCallSession) -> None:
        async with self._lock:
            if session.stream_sid in self._by_stream:
                raise DuplicateMediaSessionError(session.stream_sid)
            if session.call_id in self._stream_by_call:
                raise DuplicateMediaSessionError(str(session.call_id))
            self._by_stream[session.stream_sid] = session
            self._stream_by_call[session.call_id] = session.stream_sid

    async def get(self, stream_sid: str) -> ActiveCallSession | None:
        async with self._lock:
            return self._by_stream.get(stream_sid)

    async def close(self, stream_sid: str) -> bool:
        async with self._lock:
            session = self._by_stream.pop(stream_sid, None)
            if session is None:
                return False
            self._stream_by_call.pop(session.call_id, None)
        return await session.close()

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._by_stream.values())
            self._by_stream.clear()
            self._stream_by_call.clear()

        await asyncio.gather(
            *(session.close() for session in sessions),
            return_exceptions=True,
        )


class MediaSessionService:
    def __init__(
        self,
        *,
        database: Database,
        registry: ActiveCallRegistry,
        stt_provider: SpeechToTextProvider,
        language_model: LanguageModel,
        speech_synthesizer: SpeechSynthesizer,
    ) -> None:
        self.database = database
        self.registry = registry
        self.stt_provider = stt_provider
        self.language_model = language_model
        self.speech_synthesizer = speech_synthesizer

    async def start(
        self,
        message: StartMessage,
        *,
        audio_sink: AudioSink,
    ) -> ActiveCallSession:
        self._validate_start_message(message)

        raw_call_id = message.start.custom_parameters.get("call_id")
        try:
            call_id = UUID(raw_call_id or "")
        except ValueError as exc:
            raise InvalidMediaStartError("missing or invalid call_id") from exc

        async with self.database.session() as database_session:
            call = await CallRepository(database_session).get_by_id(call_id)

        if call is None:
            raise UnknownMediaCallError(str(call_id))
        if call.provider_call_id != message.start.call_sid:
            raise ProviderCallMismatchError(message.start.call_sid)
        if CallStatus(call.status) in TERMINAL_STATUSES:
            raise InvalidMediaStartError("cannot stream a terminal call")

        conversation = ConversationSession(
            call_id=call_id,
            language_model=self.language_model,
            response_observer=SynthesizingResponseObserver(
                call_id=call_id,
                synthesizer=self.speech_synthesizer,
                audio_sink=audio_sink,
            ),
        )
        transcriber = await self.stt_provider.open_session(
            on_transcript=conversation.on_transcript
        )
        session = ActiveCallSession(
            call_id=call_id,
            provider_call_id=message.start.call_sid,
            stream_sid=message.stream_sid,
            transcriber=transcriber,
            conversation=conversation,
        )
        try:
            await self.registry.register(session)
        except Exception:
            with suppress(Exception):
                await transcriber.close()
            raise
        return session

    async def receive_media(self, message: MediaMessage) -> None:
        session = await self.registry.get(message.stream_sid)
        if session is None:
            raise UnknownMediaStreamError(message.stream_sid)
        await session.receive_audio(message.media.decoded_audio())

    async def stop(self, message: StopMessage) -> bool:
        session = await self.registry.get(message.stream_sid)
        if session is None:
            return False
        if session.provider_call_id != message.stop.call_sid:
            raise ProviderCallMismatchError(message.stop.call_sid)
        return await self.registry.close(message.stream_sid)

    async def disconnect(self, stream_sid: str | None) -> bool:
        if stream_sid is None:
            return False
        return await self.registry.close(stream_sid)

    @staticmethod
    def _validate_start_message(message: StartMessage) -> None:
        if message.stream_sid != message.start.stream_sid:
            raise InvalidMediaStartError("conflicting stream SIDs")
        if message.start.media_format.encoding != "audio/x-mulaw":
            raise InvalidMediaStartError("unsupported audio encoding")
        if message.start.media_format.sample_rate != 8000:
            raise InvalidMediaStartError("unsupported sample rate")
        if message.start.media_format.channels != 1:
            raise InvalidMediaStartError("unsupported channel count")
        if "inbound" not in message.start.tracks:
            raise InvalidMediaStartError("inbound audio track is required")
