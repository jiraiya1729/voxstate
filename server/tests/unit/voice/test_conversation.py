import asyncio
from collections.abc import Awaitable, Callable, Sequence
from unittest.mock import Mock
from uuid import UUID

import pytest

import app.voice.conversation.response as response_module
from app.voice.conversation.response import (
    ConversationSession,
    Message,
    MessageRole,
    ModelProviderError,
)
from app.voice.conversation.synthesis import SynthesizingResponseObserver
from app.voice.conversation.transcription import TranscriptEvent, TranscriptKind
from app.voice.conversation.turns import TurnMarker, TurnState, TurnTiming

CALL_ID = UUID("00000000-0000-0000-0000-000000000001")


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class RecordingLanguageModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, tuple[Message, ...]]] = []

    async def generate(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Message],
    ) -> str:
        self.requests.append((system_prompt, tuple(messages)))
        return self.responses.pop(0)


class RecordingResponseObserver:
    def __init__(self) -> None:
        self.responses: list[tuple[UUID, str]] = []

    async def on_response(
        self,
        call_id: UUID,
        text: str,
        *,
        generation: int,
        is_current: object,
        timing: TurnTiming,
    ) -> str | None:
        del generation, is_current, timing
        self.responses.append((call_id, text))
        return None

    async def interrupt(self, call_id: UUID) -> bool:
        del call_id
        return False


@pytest.mark.asyncio
async def test_partial_and_empty_final_transcripts_do_not_call_model() -> None:
    model = RecordingLanguageModel(["unused"])
    observer = RecordingResponseObserver()
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=model,
        response_observer=observer,
    )

    await conversation.on_transcript(
        TranscriptEvent(text="hel", kind=TranscriptKind.PARTIAL)
    )
    await conversation.on_transcript(
        TranscriptEvent(text="   ", kind=TranscriptKind.FINAL)
    )

    assert model.requests == []
    assert conversation.history == ()
    assert observer.responses == []


@pytest.mark.asyncio
async def test_pause_resume_waits_for_authoritative_final_turn() -> None:
    model = RecordingLanguageModel(["Hello!"])
    observer = RecordingResponseObserver()
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=model,
        response_observer=observer,
    )

    for event in (
        TranscriptEvent(text="", kind=TranscriptKind.SPEECH_STARTED),
        TranscriptEvent(text="I need", kind=TranscriptKind.PARTIAL),
        TranscriptEvent(text="I need help", kind=TranscriptKind.EAGER_END),
        TranscriptEvent(text="", kind=TranscriptKind.RESUMED),
        TranscriptEvent(text="I need help today", kind=TranscriptKind.PARTIAL),
    ):
        await conversation.on_transcript(event)

    assert model.requests == []
    assert observer.responses == []

    await conversation.on_transcript(
        TranscriptEvent(text="I need help today", kind=TranscriptKind.FINAL)
    )
    await conversation.wait_until_idle()

    assert model.requests[0][1] == (
        Message(role=MessageRole.USER, text="I need help today"),
    )
    assert observer.responses == [(CALL_ID, "Hello!")]


@pytest.mark.asyncio
async def test_one_word_final_turn_generates_one_response() -> None:
    model = RecordingLanguageModel(["Okay."])
    observer = RecordingResponseObserver()
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=model,
        response_observer=observer,
    )

    await conversation.on_transcript(
        TranscriptEvent(text="", kind=TranscriptKind.SPEECH_STARTED)
    )
    await conversation.on_transcript(
        TranscriptEvent(text="Yes", kind=TranscriptKind.FINAL)
    )
    await conversation.wait_until_idle()

    assert len(model.requests) == 1
    assert observer.responses == [(CALL_ID, "Okay.")]


@pytest.mark.asyncio
async def test_final_turns_build_ordered_conversation_history() -> None:
    model = RecordingLanguageModel(["Hello!", "Certainly."])
    observer = RecordingResponseObserver()
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=model,
        response_observer=observer,
    )

    await conversation.on_transcript(
        TranscriptEvent(text="  Hi  ", kind=TranscriptKind.FINAL)
    )
    await conversation.wait_until_idle()
    await conversation.on_transcript(
        TranscriptEvent(text="Can you help?", kind=TranscriptKind.FINAL)
    )
    await conversation.wait_until_idle()

    assert model.requests[0][1] == (Message(role=MessageRole.USER, text="Hi"),)
    assert model.requests[1][1] == (
        Message(role=MessageRole.USER, text="Hi"),
        Message(role=MessageRole.ASSISTANT, text="Hello!"),
        Message(role=MessageRole.USER, text="Can you help?"),
    )
    assert conversation.history == (
        Message(role=MessageRole.USER, text="Hi"),
        Message(role=MessageRole.ASSISTANT, text="Hello!"),
        Message(role=MessageRole.USER, text="Can you help?"),
        Message(role=MessageRole.ASSISTANT, text="Certainly."),
    )
    assert observer.responses == [
        (CALL_ID, "Hello!"),
        (CALL_ID, "Certainly."),
    ]
    assert conversation.state is TurnState.LISTENING
    assert conversation.state_history == (
        TurnState.LISTENING,
        TurnState.THINKING,
        TurnState.SPEAKING,
        TurnState.LISTENING,
        TurnState.THINKING,
        TurnState.SPEAKING,
        TurnState.LISTENING,
    )
    assert [timing.turn_id for timing in conversation.turn_timings] == [1, 2]


@pytest.mark.asyncio
async def test_final_turn_logs_stt_and_llm_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Mock()
    monkeypatch.setattr(response_module, "logger", logger)
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=RecordingLanguageModel(["Hello!"]),
        response_observer=RecordingResponseObserver(),
    )

    await conversation.on_transcript(
        TranscriptEvent(text=" Hi there ", kind=TranscriptKind.FINAL)
    )
    await conversation.wait_until_idle()

    messages = [call.args[0] for call in logger.info.call_args_list]
    debug_messages = [call.args[0] for call in logger.debug.call_args_list]
    assert "voice.stt.final call_id=%s chars=%d" in messages
    assert "voice.stt.text call_id=%s text=%r" in debug_messages
    assert "voice.llm.request call_id=%s turns=%d" in messages
    assert "voice.llm.response call_id=%s elapsed_ms=%.1f chars=%d" in messages
    assert "voice.llm.text call_id=%s text=%r" in debug_messages


@pytest.mark.asyncio
async def test_failed_model_turn_is_not_committed_to_history() -> None:
    class FailingLanguageModel:
        async def generate(
            self,
            *,
            system_prompt: str,
            messages: Sequence[Message],
        ) -> str:
            raise ModelProviderError("failed")

    observer = RecordingResponseObserver()
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=FailingLanguageModel(),
        response_observer=observer,
    )

    await conversation.on_transcript(
        TranscriptEvent(text="Hello", kind=TranscriptKind.FINAL)
    )
    with pytest.raises(ModelProviderError):
        await conversation.wait_until_idle()

    assert conversation.history == ()
    assert observer.responses == []
    assert conversation.state is TurnState.LISTENING


@pytest.mark.asyncio
async def test_model_failure_is_logged_and_propagated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingLanguageModel:
        async def generate(
            self,
            *,
            system_prompt: str,
            messages: Sequence[Message],
        ) -> str:
            raise ModelProviderError("failed")

    logger = Mock()
    monkeypatch.setattr(response_module, "logger", logger)
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=FailingLanguageModel(),
        response_observer=RecordingResponseObserver(),
    )

    await conversation.on_transcript(
        TranscriptEvent(text="Hello", kind=TranscriptKind.FINAL)
    )
    with pytest.raises(ModelProviderError):
        await conversation.wait_until_idle()

    assert logger.exception.call_args.args[0] == (
        "voice.llm.error call_id=%s elapsed_ms=%.1f"
    )


@pytest.mark.asyncio
async def test_response_failure_restores_listening_state() -> None:
    class FailingObserver:
        async def on_response(
            self,
            call_id: UUID,
            text: str,
            *,
            generation: int,
            is_current: object,
            timing: TurnTiming,
        ) -> str | None:
            del call_id, text, generation, is_current, timing
            raise RuntimeError("playback failed")

        async def interrupt(self, call_id: UUID) -> bool:
            del call_id
            return False

    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=RecordingLanguageModel(["Hello!"]),
        response_observer=FailingObserver(),
    )

    await conversation.on_transcript(
        TranscriptEvent(text="Hello", kind=TranscriptKind.FINAL)
    )
    with pytest.raises(RuntimeError, match="playback failed"):
        await conversation.wait_until_idle()

    assert conversation.state is TurnState.LISTENING


@pytest.mark.asyncio
async def test_close_is_terminal_and_idempotent() -> None:
    model = RecordingLanguageModel(["unused"])
    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=model,
        response_observer=RecordingResponseObserver(),
    )

    assert await conversation.close() is True
    assert await conversation.close() is False
    await conversation.on_transcript(
        TranscriptEvent(text="Hello", kind=TranscriptKind.FINAL)
    )

    assert conversation.state is TurnState.CLOSED
    assert model.requests == []


@pytest.mark.asyncio
async def test_speech_during_playback_clears_and_rejects_late_audio() -> None:
    class LateChunkSynthesizer:
        def __init__(self) -> None:
            self.first_chunk_sent = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def synthesize(
            self,
            text: str,
            *,
            on_audio: Callable[[bytes], Awaitable[None]],
        ) -> None:
            del text
            await on_audio(b"current")
            self.first_chunk_sent.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await on_audio(b"stale")
                self.cancelled.set()
                raise

    synthesizer = LateChunkSynthesizer()
    playback: list[bytes] = []
    clears: list[bool] = []

    async def capture_audio(audio: bytes) -> None:
        playback.append(audio)

    async def clear_audio() -> None:
        clears.append(True)

    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=RecordingLanguageModel(["Long response"]),
        response_observer=SynthesizingResponseObserver(
            call_id=CALL_ID,
            synthesizer=synthesizer,
            audio_sink=capture_audio,
            clear_sink=clear_audio,
        ),
    )

    await conversation.on_transcript(
        TranscriptEvent(text="Hello", kind=TranscriptKind.FINAL)
    )
    await asyncio.wait_for(synthesizer.first_chunk_sent.wait(), timeout=1)
    assert conversation.state is TurnState.SPEAKING

    await conversation.on_transcript(
        TranscriptEvent(text="", kind=TranscriptKind.SPEECH_STARTED)
    )

    assert synthesizer.cancelled.is_set()
    assert playback == [b"current"]
    assert clears == [True]
    assert conversation.state is TurnState.LISTENING
    assert TurnState.INTERRUPTED in conversation.state_history


@pytest.mark.asyncio
async def test_twilio_mark_moves_speaking_turn_back_to_listening() -> None:
    class OneChunkSynthesizer:
        async def synthesize(
            self,
            text: str,
            *,
            on_audio: Callable[[bytes], Awaitable[None]],
        ) -> None:
            del text
            await on_audio(b"audio")

    marks: list[str] = []

    async def discard_audio(audio: bytes) -> None:
        del audio

    async def mark_audio(name: str) -> None:
        marks.append(name)

    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=RecordingLanguageModel(["Response"]),
        response_observer=SynthesizingResponseObserver(
            call_id=CALL_ID,
            synthesizer=OneChunkSynthesizer(),
            audio_sink=discard_audio,
            mark_sink=mark_audio,
        ),
    )

    await conversation.on_transcript(
        TranscriptEvent(text="Hello", kind=TranscriptKind.FINAL)
    )
    await conversation.wait_until_idle()

    assert marks == ["turn-1"]
    assert conversation.state is TurnState.SPEAKING
    assert await conversation.on_playback_complete("another-turn") is False
    assert await conversation.on_playback_complete("turn-1") is True
    assert await conversation.on_playback_complete("turn-1") is False
    assert conversation.state is TurnState.LISTENING


@pytest.mark.asyncio
async def test_completed_turn_reports_correlated_latency_boundaries() -> None:
    clock = FakeClock(1.0)

    class TimedModel:
        async def generate(
            self,
            *,
            system_prompt: str,
            messages: Sequence[Message],
        ) -> str:
            del system_prompt, messages
            clock.advance(0.2)
            return "Response"

    class TimedSynthesizer:
        async def synthesize(
            self,
            text: str,
            *,
            on_audio: Callable[[bytes], Awaitable[None]],
        ) -> None:
            del text
            clock.advance(0.3)
            await on_audio(b"audio")

    marks: list[str] = []

    async def send_audio(audio: bytes) -> None:
        del audio
        clock.advance(0.05)

    async def mark_audio(name: str) -> None:
        marks.append(name)

    conversation = ConversationSession(
        call_id=CALL_ID,
        language_model=TimedModel(),
        response_observer=SynthesizingResponseObserver(
            call_id=CALL_ID,
            synthesizer=TimedSynthesizer(),
            audio_sink=send_audio,
            mark_sink=mark_audio,
        ),
        clock=clock,
    )

    await conversation.on_transcript(
        TranscriptEvent(text="", kind=TranscriptKind.SPEECH_STARTED)
    )
    clock.advance(0.4)
    await conversation.on_transcript(
        TranscriptEvent(text="Hello", kind=TranscriptKind.EAGER_END)
    )
    clock.advance(0.1)
    await conversation.on_transcript(
        TranscriptEvent(text="Hello", kind=TranscriptKind.FINAL)
    )
    await conversation.wait_until_idle()
    clock.advance(0.1)
    await conversation.on_playback_complete(marks[0])

    timing = conversation.turn_timings[0]
    assert timing.timestamp(TurnMarker.COMPLETED) == pytest.approx(2.15)
    assert timing.stt_latency_ms == pytest.approx(100)
    assert timing.llm_latency_ms == pytest.approx(200)
    assert timing.tts_first_byte_ms == pytest.approx(300)
    assert timing.response_latency_ms == pytest.approx(650)
